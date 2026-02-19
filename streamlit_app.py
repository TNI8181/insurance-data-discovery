import re
from io import BytesIO

import pandas as pd
import streamlit as st


# -------------------------------
# Helpers
# -------------------------------
def normalize_col(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)  # spaces, hyphens, slashes -> _
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def apply_synonyms(homogenized: str, synonyms_df: pd.DataFrame) -> str:
    """
    Apply user-maintained regex synonym rules (enabled rows only).
    Each rule: pattern -> replacement
    """
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
            # If a rule is malformed, skip it (don’t break the app)
            continue

    s = re.sub(r"_+", "_", s).strip("_")
    return s


def base_homogenize(norm: str) -> str:
    """
    Lightweight default homogenisation (starter rules).
    This runs BEFORE user synonyms.
    """
    s = norm

    # Common insurance/reporting synonyms (starter set)
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
            safe_sheet = sheet_name[:31]  # Excel sheet name limit
            df.to_excel(writer, sheet_name=safe_sheet, index=False)
    output.seek(0)
    return output.getvalue()


def build_report_rationalization(field_df: pd.DataFrame) -> pd.DataFrame:
    """
    Basic report rationalisation scoring using homogenized fields.

    Metrics per report:
    - total_fields: count of homogenized field instances in the report (unique)
    - unique_fields: fields that appear only in this report across all reports
    - uniqueness_ratio: unique_fields / total_fields
    - avg_jaccard_overlap: average overlap with other reports (0..1)
    - recommendation: Keep / Merge / Review
    """
    if field_df.empty:
        return pd.DataFrame()

    # Build set of homogenized fields per report
    report_fields = (
        field_df.groupby("report_name")["column_homogenized"]
        .apply(lambda s: set(s.dropna().astype(str).tolist()))
        .to_dict()
    )

    # Count in how many reports each homogenized field appears
    field_counts = (
        field_df[["report_name", "column_homogenized"]]
        .drop_duplicates()
        .groupby("column_homogenized")["report_name"]
        .nunique()
    )

    reports = list(report_fields.keys())
    rows = []

    # Precompute Jaccard overlaps
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

        # Simple recommendation logic (tweak later)
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


# -------------------------------
# Business definition suggestions (starter library)
# Expand this over time (your IP)
# -------------------------------
DEFINITION_SUGGESTIONS = {
    "policy_number": "Unique identifier for an insurance policy.",
    "claim_number": "Unique identifier for an insurance claim.",
    "account_id": "Identifier for the customer/account associated with the policy.",
    "loss_date": "Date on which the loss event occurred.",
    "report_date": "Date the loss/claim was first reported to the carrier.",
    "effective_date": "Policy start date (coverage begins).",
    "expiration_date": "Policy end date (coverage ends).",
    "written_premium": "Premium written for the policy term (may differ from earned premium).",
    "total_incurred": "Total incurred amount (paid + reserved).",
    "total_paid": "Total amount paid to date on the claim.",
    "current_reserve": "Current outstanding reserve amount on the claim.",
    "payment_date": "Date the payment transaction was issued/recorded.",
    "payment_amount": "Amount paid in a payment transaction.",
}

# -------------------------------
# Page Config
# -------------------------------
st.set_page_config(page_title="Insurance Data Discovery", layout="wide")

st.title("Insurance Data Discovery Tool (Module 1)")
st.caption(
    "Upload sample reports (Excel/CSV). We'll extract fields, normalize/homogenize, cross-tab, "
    "generate definitions, score report rationalisation, and export everything to Excel."
)

# -------------------------------
# Inputs
# -------------------------------
source_system = st.text_input("Source System Name (e.g., Legacy PAS, Mainframe Claims)")

uploaded_files = st.file_uploader(
    "Upload report files",
    type=["xlsx", "csv"],
    accept_multiple_files=True
)

analyze = st.button("Analyze Reports", type="primary")

# -------------------------------
# Main Processing
# -------------------------------
if analyze:
    if not uploaded_files:
        st.warning("Please upload at least one Excel or CSV report.")
        st.stop()

    if not source_system.strip():
        st.warning("Please enter a Source System Name.")
        st.stop()

    st.success(f"Uploaded {len(uploaded_files)} file(s) for Source System: {source_system}")

    # -------------------------------
    # Synonym Rules (Editable, no code changes needed later)
    # -------------------------------
    st.write("## Synonym Rules (Editable)")
    st.caption(
        "These rules help homogenize field names (regex pattern → replacement). "
        "Example: pattern = r'^pol_?no$' replacement = 'policy_number'"
    )

    if "synonyms_df" not in st.session_state:
        st.session_state["synonyms_df"] = pd.DataFrame([
            {"enabled": "Y", "pattern": r"^pol(?:icy)?_?no$", "replacement": "policy_number"},
            {"enabled": "Y", "pattern": r"^policy_?number$", "replacement": "policy_number"},
            {"enabled": "Y", "pattern": r"^claim_?no$", "replacement": "claim_number"},
            {"enabled": "Y", "pattern": r"^claim_?number$", "replacement": "claim_number"},
        ])

    synonyms_df = st.data_editor(
        st.session_state["synonyms_df"],
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "enabled": st.column_config.SelectboxColumn(
                "enabled", options=["Y", "N"], required=True
            ),
            "pattern": st.column_config.TextColumn(
                "pattern", help="Regex pattern (Python). Example: ^pol(?:icy)?_?no$"
            ),
            "replacement": st.column_config.TextColumn(
                "replacement", help="Replacement value. Example: policy_number"
            ),
        }
    )
    st.session_state["synonyms_df"] = synonyms_df

    # -------------------------------
    # Uploaded files list
    # -------------------------------
    st.write("## Uploaded Files")
    for f in uploaded_files:
        st.write(f"• {f.name}")

    # -------------------------------
    # Quick Profiling
    # -------------------------------
    st.write("## Quick Profiling (Preview)")
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
                    "sample_columns": ", ".join([str(c) for c in df.columns[:10]])
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
                        "sample_columns": ", ".join([str(c) for c in df.columns[:10]])
                    })
        except Exception as e:
            st.error(f"Could not read {f.name}: {e}")

    profile_df = pd.DataFrame(profile_rows)
    st.dataframe(profile_df, use_container_width=True)

    # -------------------------------
    # Field Inventory (Raw + Normalized + Homogenized)
    # -------------------------------
    st.write("## Field Inventory (Raw + Normalized + Homogenized)")

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

    if field_df.empty:
        st.warning("No fields were extracted. Please try different files.")
        st.stop()

    # -------------------------------
    # Business Definitions (Editable) + Auto-suggestions
    # -------------------------------
    st.write("## Business Definitions (Editable)")
    st.caption("Definitions are maintained per HOMOGENIZED field name.")

    distinct_fields = (
        field_df[["column_homogenized"]]
        .drop_duplicates()
        .sort_values("column_homogenized")
        .reset_index(drop=True)
    )

    # Reset definitions if source_system changes (simple approach for now)
    if "definitions_df" not in st.session_state or st.session_state.get("definitions_source") != source_system:
        defs = distinct_fields.copy()
        defs["include_flag"] = "Y"

        # Prefill suggested definitions if available
        defs["business_definition"] = defs["column_homogenized"].apply(
            lambda k: DEFINITION_SUGGESTIONS.get(str(k), "")
        )

        st.session_state["definitions_df"] = defs
        st.session_state["definitions_source"] = source_system

    edited_definitions = st.data_editor(
        st.session_state["definitions_df"],
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "include_flag": st.column_config.SelectboxColumn(
                "include_flag",
                help="Y = include in outputs, N = exclude",
                options=["Y", "N"],
                required=True
            ),
            "business_definition": st.column_config.TextColumn(
                "business_definition",
                help="Plain-English meaning (auto-suggested when possible)"
            )
        }
    )

    st.session_state["definitions_df"] = edited_definitions

    # Join definitions back into field_df
    field_df = field_df.merge(
        edited_definitions[["column_homogenized", "include_flag", "business_definition"]],
        on="column_homogenized",
        how="left"
    )

    st.write("### Full Field Inventory (with definitions)")
    st.dataframe(field_df, use_container_width=True)

    # -------------------------------
    # Distinct Field Summary Metrics
    # -------------------------------
    st.write("## Summary Metrics")

    total_reports = field_df["report_name"].nunique()
    total_field_instances = len(field_df)

    distinct_original = field_df["column_original"].nunique()
    distinct_normalized = field_df["column_normalized"].nunique()
    distinct_homogenized = field_df["column_homogenized"].nunique()

    included = edited_definitions[edited_definitions["include_flag"] == "Y"].copy()
    missing_defs = int((included["business_definition"].fillna("").str.strip() == "").sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Reports", total_reports)
    c2.metric("Field Instances", total_field_instances)
    c3.metric("Distinct Original", distinct_original)
    c4.metric("Distinct Normalized", distinct_normalized)
    c5.metric("Distinct Homogenized", distinct_homogenized)

    st.info(f"Included fields missing business definition: {missing_defs}")

    # -------------------------------
    # Cross Tabs (Original + Homogenized)
    # -------------------------------
    st.write("## Cross Tabs")

    st.write("### Cross Tab (Original Column Names) — X = Present")
    ct_orig = pd.crosstab(field_df["column_original"], field_df["report_name"])
    ct_orig = ct_orig.applymap(lambda v: "X" if v > 0 else "")
    st.dataframe(ct_orig, use_container_width=True)

    st.write("### Cross Tab (Homogenized Column Names) — X = Present")
    ct_homo = pd.crosstab(field_df["column_homogenized"], field_df["report_name"])
    ct_homo = ct_homo.applymap(lambda v: "X" if v > 0 else "")
    st.dataframe(ct_homo, use_container_width=True)

    # -------------------------------
    # Report Rationalisation Scoring
    # -------------------------------
    st.write("## Report Rationalisation (Scoring)")
    rational_df = build_report_rationalization(field_df)

    st.caption(
        "Interpretation: higher overlap + low uniqueness ⇒ likely redundant. "
        "This is an initial heuristic (we’ll tune it)."
    )
    st.dataframe(rational_df, use_container_width=True)

    # -------------------------------
    # Download to Excel
    # -------------------------------
    st.write("## Download Output")

    export_only_included = st.checkbox("Export only include_flag = Y", value=True)

    if export_only_included:
        dictionary_export = edited_definitions[edited_definitions["include_flag"] == "Y"].reset_index(drop=True)
        field_export = field_df[field_df["include_flag"] == "Y"].reset_index(drop=True)
    else:
        dictionary_export = edited_definitions.copy()
        field_export = field_df.copy()

    excel_bytes = df_to_excel_bytes({
        "__Quick_Profile": profile_df,
        "__Synonym_Rules": synonyms_df,
        "__Field_Inventory": field_export,
        "__Distinct_Fields": dictionary_export,
        "__CrossTab_Original": ct_orig.reset_index().rename(columns={"column_original": "field"}),
        "__CrossTab_Homogenized": ct_homo.reset_index().rename(columns={"column_homogenized": "field"}),
        "__Report_Rationalisation": rational_df,
    })

    st.download_button(
        label="Download Excel Output",
        data=excel_bytes,
        file_name=f"data_discovery_output_{source_system.strip().replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
