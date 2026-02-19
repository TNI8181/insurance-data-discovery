import re
from io import BytesIO

import pandas as pd
import streamlit as st


# -------------------------------
# Helpers
# -------------------------------
def normalize_col(name: str) -> str:
    """
    Simple, deterministic normalization:
    - lower case
    - replace non-alphanumeric with underscores
    - collapse underscores
    - strip underscores
    """
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def homogenize_col(norm: str) -> str:
    """
    Lightweight homogenisation (rule-based aliases).
    Add more rules over time (this becomes your IP).
    """
    s = norm

    # Common insurance/reporting synonyms (starter set)
    s = re.sub(r"\bpol(?:icy)?_?no\b", "policy_number", s)
    s = re.sub(r"\bpolicy_?number\b", "policy_number", s)
    s = re.sub(r"\bclaim_?no\b", "claim_number", s)
    s = re.sub(r"\bclaim_?number\b", "claim_number", s)
    s = re.sub(r"\bacct_?id\b", "account_id", s)
    s = re.sub(r"\bloss_?dt\b", "loss_date", s)
    s = re.sub(r"\breport_?dt\b", "report_date", s)
    s = re.sub(r"\beff(?:ective)?_?date\b", "effective_date", s)
    s = re.sub(r"\bexp(?:iration)?_?date\b", "expiration_date", s)

    # Keep it clean again
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def df_to_excel_bytes(dfs_by_sheetname: dict) -> bytes:
    """
    Create an in-memory Excel file from multiple DataFrames.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dfs_by_sheetname.items():
            safe_sheet = sheet_name[:31]  # Excel sheet name limit
            df.to_excel(writer, sheet_name=safe_sheet, index=False)
    output.seek(0)
    return output.getvalue()


# -------------------------------
# Page Config
# -------------------------------
st.set_page_config(page_title="Insurance Data Discovery", layout="wide")

st.title("Insurance Data Discovery Tool (Module 1)")
st.caption(
    "Upload sample reports (Excel/CSV). We'll extract column metadata, normalize/homogenize fields, "
    "cross-tab them, and generate an Excel output you can download."
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
                    col_homo = homogenize_col(col_norm)
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
                        col_homo = homogenize_col(col_norm)
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
    # Business Definition (editable)
    # -------------------------------
    st.write("## Business Definitions (Editable)")

    # Distinct list based on homogenized (best grouping for business definitions)
    distinct_fields = (
        field_df[["column_homogenized"]]
        .drop_duplicates()
        .sort_values("column_homogenized")
        .reset_index(drop=True)
    )

    # Create editable table: business_definition + include_flag
    # Use session state to preserve edits between reruns
    if "definitions_df" not in st.session_state or st.session_state.get("definitions_source") != source_system:
        defs = distinct_fields.copy()
        defs["include_flag"] = "Y"
        defs["business_definition"] = ""
        st.session_state["definitions_df"] = defs
        st.session_state["definitions_source"] = source_system

    definitions_df = st.session_state["definitions_df"]

    edited_definitions = st.data_editor(
        definitions_df,
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
                help="Write a plain-English definition for the field"
            )
        }
    )

    # Persist edits
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
    total_fields_instances = len(field_df)  # field occurrences across reports
    distinct_original = field_df["column_original"].nunique()
    distinct_normalized = field_df["column_normalized"].nunique()
    distinct_homogenized = field_df["column_homogenized"].nunique()

    unresolved_definitions = int((edited_definitions["include_flag"] == "Y").sum() - (edited_definitions.loc[edited_definitions["include_flag"] == "Y", "business_definition"].fillna("").str.strip() != "").sum())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Reports", total_reports)
    c2.metric("Field Instances", total_fields_instances)
    c3.metric("Distinct Original", distinct_original)
    c4.metric("Distinct Normalized", distinct_normalized)
    c5.metric("Distinct Homogenized", distinct_homogenized)

    st.info(f"Included fields missing business definition: {unresolved_definitions}")

    # -------------------------------
    # Cross Tabs (Original + Homogenized)
    # -------------------------------
    st.write("## Cross Tabs")

    # Original columns (exact headers)
    st.write("### Cross Tab (Original Column Names) — X = Present")
    ct_orig = pd.crosstab(field_df["column_original"], field_df["report_name"])
    ct_orig = ct_orig.applymap(lambda v: "X" if v > 0 else "")
    st.dataframe(ct_orig, use_container_width=True)

    # Homogenized columns (best for rationalization)
    st.write("### Cross Tab (Homogenized Column Names) — X = Present")
    ct_homo = pd.crosstab(field_df["column_homogenized"], field_df["report_name"])
    ct_homo = ct_homo.applymap(lambda v: "X" if v > 0 else "")
    st.dataframe(ct_homo, use_container_width=True)

    # -------------------------------
    # Download to Excel
    # -------------------------------
    st.write("## Download Output")

    # Create distinct list for export (like a mini data dictionary)
    dictionary_export = edited_definitions.copy()

    # Optional: only include Y
    export_only_included = st.checkbox("Export only include_flag = Y", value=True)
    if export_only_included:
        dictionary_export = dictionary_export[dictionary_export["include_flag"] == "Y"].reset_index(drop=True)
        field_export = field_df[field_df["include_flag"] == "Y"].reset_index(drop=True)
    else:
        field_export = field_df.copy()

    excel_bytes = df_to_excel_bytes({
        "__Field_Inventory": field_export,
        "__Distinct_Fields": dictionary_export,
        "__CrossTab_Original": ct_orig.reset_index().rename(columns={"column_original": "field"}),
        "__CrossTab_Homogenized": ct_homo.reset_index().rename(columns={"column_homogenized": "field"}),
        "__Quick_Profile": profile_df
    })

    st.download_button(
        label="Download Excel Output",
        data=excel_bytes,
        file_name=f"data_discovery_output_{source_system.strip().replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
