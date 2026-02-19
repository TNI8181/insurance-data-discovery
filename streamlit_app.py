import re
from io import BytesIO

import pandas as pd
import streamlit as st


# -------------------------------
# Helpers
# -------------------------------
def normalize_col(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def apply_synonyms(homogenized: str, synonyms_df: pd.DataFrame) -> str:
    s = homogenized
    if synonyms_df is None or synonyms_df.empty:
        return s

    for _, row in synonyms_df.iterrows():
        try:
            if str(row.get("enabled", "Y")).strip().upper() != "Y":
                continue
            pattern = str(row.get("pattern", "")).strip()
            repl = str(row.get("replacement", "")).strip()
            if not pattern:
                continue
            s = re.sub(pattern, repl, s)
        except Exception:
            continue

    s = re.sub(r"_+", "_", s).strip("_")
    return s


def base_homogenize(norm: str) -> str:
    s = norm

    s = re.sub(r"\bpol(?:icy)?_?no\b", "policy_number", s)
    s = re.sub(r"\bpolicy_?number\b", "policy_number", s)

    s = re.sub(r"\bclaim_?no\b", "claim_number", s)
    s = re.sub(r"\bclaim_?number\b", "claim_number", s)

    s = re.sub(r"\bacct_?id\b", "account_id", s)

    s = re.sub(r"\bloss_?dt\b", "loss_date", s)
    s = re.sub(r"\bloss_?date\b", "loss_date", s)

    s = re.sub(r"\breport_?dt\b", "report_date", s)
    s = re.sub(r"\breport_?date\b", "report_date", s)

    s = re.sub(r"\beff(?:ective)?_?date\b", "effective_date", s)
    s = re.sub(r"\bexp(?:iration)?_?date\b", "expiration_date", s)

    s = re.sub(r"_+", "_", s).strip("_")
    return s


def df_to_excel_bytes(dfs_by_sheetname: dict) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dfs_by_sheetname.items():
            safe_sheet = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_sheet, index=False)
    output.seek(0)
    return output.getvalue()


def build_report_rationalization(field_df: pd.DataFrame) -> pd.DataFrame:
    if field_df.empty:
        return pd.DataFrame()

    report_fields = (
        field_df.groupby("report_name")["column_homogenized"]
        .apply(lambda s: set(s.dropna().astype(str).tolist()))
        .to_dict()
    )

    field_counts = (
        field_df[["report_name", "column_homogenized"]]
        .drop_duplicates()
        .groupby("column_homogenized")["report_name"]
        .nunique()
    )

    reports = list(report_fields.keys())
    rows = []

    def jaccard(a: set, b: set) -> float:
        if not a and not b:
            return 0.0
        return len(a & b) / len(a | b)

    for r in reports:
        fields = report_fields[r]
        total_fields = len(fields)
        unique_fields = sum(1 for f in fields if field_counts.get(f, 0) == 1)
        uniqueness_ratio = (unique_fields / total_fields) if total_fields else 0.0

        overlaps = []
        for other in reports:
            if other == r:
                continue
            overlaps.append(jaccard(fields, report_fields[other]))

        avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0

        if total_fields == 0:
            rec = "Review"
        elif uniqueness_ratio >= 0.35:
            rec = "Keep"
        elif avg_overlap >= 0.70:
            rec = "Merge"
        else:
            rec = "Review"

        rows.append({
            "report_name": r,
            "total_fields": total_fields,
            "unique_fields": unique_fields,
            "uniqueness_ratio": round(uniqueness_ratio, 3),
            "avg_jaccard_overlap": round(avg_overlap, 3),
            "recommendation": rec
        })

    return pd.DataFrame(rows).sort_values(
        ["recommendation", "avg_jaccard_overlap", "uniqueness_ratio"],
        ascending=[True, False, True]
    )


# -------------------------------------------
# Business definitions (starter library)
# -------------------------------------------
DEFINITION_SUGGESTIONS = {
    "policy_number": "Unique identifier for an insurance policy.",
    "claim_number": "Unique identifier for an insurance claim.",
    "account_id": "Identifier for the customer/account associated with the policy.",
    "loss_date": "Date on which the loss event occurred.",
    "report_date": "Date the loss/claim was first reported.",
    "effective_date": "Policy start date.",
    "expiration_date": "Policy end date.",
    "written_premium": "Premium written for the policy term.",
    "total_incurred": "Paid + reserved amounts.",
    "total_paid": "Total paid on the claim.",
    "current_reserve": "Outstanding reserve.",
    "payment_date": "Date of a payment transaction.",
    "payment_amount": "Amount paid.",
}


# -------------------------------
# Page Config
# -------------------------------
st.set_page_config(page_title="Insurance Data Discovery", layout="wide")

st.title("Insurance Data Discovery Tool (Module 1)")
st.caption("Upload reports → Extract & Homogenize → Cross Tabs → Rationalisation → Excel Output")


# -------------------------------
# Inputs
# -------------------------------
source_system = st.text_input("Source System Name")

uploaded_files = st.file_uploader(
    "Upload Excel/CSV reports",
    type=["xlsx", "csv"],
    accept_multiple_files=True
)

analyze = st.button("Analyze Reports", type="primary")


# -------------------------------
# MAIN PROCESSING
# -------------------------------
if analyze:
    if not uploaded_files:
        st.warning("Upload at least one file.")
        st.stop()

    if not source_system.strip():
        st.warning("Enter a source system name.")
        st.stop()

    # Synonym rules
    st.write("## Synonym Rules")
    if "synonyms_df" not in st.session_state:
        st.session_state["synonyms_df"] = pd.DataFrame([
            {"enabled": "Y", "pattern": r"^pol(?:icy)?_?no$", "replacement": "policy_number"},
            {"enabled": "Y", "pattern": r"^claim_?no$", "replacement": "claim_number"},
        ])

    synonyms_df = st.data_editor(
        st.session_state["synonyms_df"],
        use_container_width=True,
        num_rows="dynamic"
    )
    st.session_state["synonyms_df"] = synonyms_df

    # Profiling
    st.write("## Profiling")
    profile_rows = []
    for f in uploaded_files:
        try:
            if f.name.lower().endswith(".csv"):
                df = pd.read_csv(f)
                profile_rows.append({
                    "file_name": f.name,
                    "sheet_name": "(csv)",
                    "rows": len(df),
                    "columns": len(df.columns),
                    "sample_columns": ", ".join(map(str, df.columns[:10]))
                })
            else:
                xls = pd.ExcelFile(f)
                for sheet in xls.sheet_names:
                    df = xls.parse(sheet)
                    profile_rows.append({
                        "file_name": f.name,
                        "sheet_name": sheet,
                        "rows": len(df),
                        "columns": len(df.columns),
                        "sample_columns": ", ".join(map(str, df.columns[:10]))
                    })
        except Exception as e:
            st.error(f"Could not read {f.name}: {e}")

    profile_df = pd.DataFrame(profile_rows)

    # Field inventory
    field_rows = []
    for f in uploaded_files:
        try:
            if f.name.lower().endswith(".csv"):
                df = pd.read_csv(f)
                report_label = f"{f.name} | (csv)"
                for col in df.columns:
                    col_orig = str(col)
                    col_norm = normalize_col(col_orig)
                    col_base = base_homogenize(col_norm)
                    col_homo = apply_synonyms(col_base, synonyms_df)
                    field_rows.append({
                        "source_system": source_system,
                        "file_name": f.name,
                        "sheet_name": "(csv)",
                        "report_name": report_label,
                        "column_original": col_orig,
                        "column_normalized": col_norm,
                        "column_homogenized": col_homo,
                    })
            else:
                xls = pd.ExcelFile(f)
                for sheet in xls.sheet_names:
                    df = xls.parse(sheet)
                    report_label = f"{f.name} | {sheet}"
                    for col in df.columns:
                        col_orig = str(col)
                        col_norm = normalize_col(col_orig)
                        col_base = base_homogenize(col_norm)
                        col_homo = apply_synonyms(col_base, synonyms_df)
                        field_rows.append({
                            "source_system": source_system,
                            "file_name": f.name,
                            "sheet_name": sheet,
                            "report_name": report_label,
                            "column_original": col_orig,
                            "column_normalized": col_norm,
                            "column_homogenized": col_homo,
                        })
        except Exception as e:
            st.error(f"Could not process {f.name}: {e}")

    field_df = pd.DataFrame(field_rows)

    # Definitions
    st.write("## Business Definitions")
    distinct_fields = field_df[["column_homogenized"]].drop_duplicates().sort_values("column_homogenized")

    if "definitions_df" not in st.session_state or st.session_state.get("definitions_source") != source_system:
        defs = distinct_fields.copy()
        defs["include_flag"] = "Y"
        defs["business_definition"] = defs["column_homogenized"].apply(lambda x: DEFINITION_SUGGESTIONS.get(x, ""))
        st.session_state["definitions_df"] = defs
        st.session_state["definitions_source"] = source_system

    edited_definitions = st.data_editor(
        st.session_state["definitions_df"],
        use_container_width=True,
        num_rows="fixed"
    )

    st.session_state["definitions_df"] = edited_definitions

    # Merge definitions into field_df
    field_df = field_df.merge(
        edited_definitions[["column_homogenized", "include_flag", "business_definition"]],
        on="column_homogenized",
        how="left"
    )

    # Create tabs
    tab1, tab2, tab3 = st.tabs(["Discovery", "Cross Tabs", "Homogenisation Report"])

    # TAB 1 — DISCOVERY
    with tab1:
        st.write("## Profiling")
        st.dataframe(profile_df, use_container_width=True)

        st.write("## Field Inventory")
        st.dataframe(field_df, use_container_width=True)

        st.write("## Business Definitions")
        st.dataframe(edited_definitions, use_container_width=True)

    # TAB 2 — CROSS TABS
    with tab2:
        st.write("## Cross Tab — Original")
        ct_orig = pd.crosstab(field_df["column_original"], field_df["report_name"])
        ct_orig = ct_orig.applymap(lambda v: "X" if v > 0 else "")
        st.dataframe(ct_orig, use_container_width=True)

        st.write("## Cross Tab — Homogenised")
        ct_homo = pd.crosstab(field_df["column_homogenized"], field_df["report_name"])
        ct_homo = ct_homo.applymap(lambda v: "X" if v > 0 else "")
        st.dataframe(ct_homo, use_container_width=True)

        st.write("## Report Rationalisation")
        rational_df = build_report_rationalization(field_df)
        st.dataframe(rational_df, use_container_width=True)

    # TAB 3 — HOMOGENISATION REPORT
    with tab3:
        # A) Transformation Journey
        st.write("### A) Transformation Journey")
        transform_df = field_df[[
            "report_name",
            "column_original",
            "column_normalized",
            "column_homogenized"
        ]].copy()
        transform_df["column_base_homogenized"] = transform_df["column_normalized"].apply(base_homogenize)
        st.dataframe(transform_df, use_container_width=True)

        # B) Collapse Summary
        st.write("### B) Collapse Summary (Variants → Final Field)")
        collapse_df = (
            field_df.groupby("column_homogenized")["column_original"]
            .unique()
            .reset_index()
            .rename(columns={"column_original": "variants"})
        )
        collapse_df["variant_count"] = collapse_df["variants"].apply(len)
        st.dataframe(collapse_df, use_container_width=True)

        # C) Unmatched Fields
        st.write("### C) Unmatched Fields")
        unmatched_df = transform_df[
            transform_df["column_normalized"] == transform_df["column_homogenized"]
        ]
        st.dataframe(unmatched_df, use_container_width=True)

        # D) Synonym Rule Effectiveness
        st.write("### D) Synonym Rule Effectiveness")
        eff_rows = []
        for _, row in synonyms_df.iterrows():
            pattern = row["pattern"]
            replacement = row["replacement"]
            enabled = row["enabled"]
            matched = transform_df["column_base_homogenized"].str.contains(pattern, regex=True).sum() if enabled == "Y" else 0
            eff_rows.append({
                "pattern": pattern,
                "replacement": replacement,
                "enabled": enabled,
                "matched_fields": matched
            })
        eff_df = pd.DataFrame(eff_rows)
        st.dataframe(eff_df, use_container_width=True)

        # E) Confidence
        st.write("### E) Confidence Score")
        def score_conf(row):
            base = base_homogenize(row["column_normalized"])
            final = row["column_homogenized"]
            if base != row["column_normalized"] and final != base:
                return "High"
            elif base != row["column_normalized"] and final == base:
                return "Medium"
            else:
                return "Low"

        conf_df = transform_df.copy()
        conf_df["confidence"] = conf_df.apply(score_conf, axis=1)
        st.dataframe(conf_df, use_container_width=True)

    # -------------------------------
    # DOWNLOAD
    # -------------------------------
    st.write("## Download Output")

    export_only = st.checkbox("Export only include_flag = Y", value=True)

    if export_only:
        dict_export = edited_definitions[edited_definitions["include_flag"] == "Y"]
        field_export = field_df[field_df["include_flag"] == "Y"]
    else:
        dict_export = edited_definitions.copy()
        field_export = field_df.copy()

    excel_bytes = df_to_excel_bytes({
        "__Profile": profile_df,
        "__Synonym_Rules": synonyms_df,
        "__Definitions": dict_export,
        "__Field_Inventory": field_export,
        "__CrossTab_Original": ct_orig.reset_index(),
        "__CrossTab_Homogenized": ct_homo.reset_index(),
        "__Rationalisation": rational_df,
        "__Transform": transform_df,
        "__Collapse": collapse_df,
        "__Unmatched": unmatched_df,
        "__Synonym_Effectiveness": eff_df,
        "__Confidence": conf_df
    })

    st.download_button(
        "Download Excel Output",
        data=excel_bytes,
        file_name="data_discovery_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
