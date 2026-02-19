import streamlit as st
import pandas as pd

# -------------------------------
# Page Config
# -------------------------------
st.set_page_config(page_title="Insurance Data Discovery", layout="wide")

st.title("Insurance Data Discovery Tool (Module 1)")
st.caption("Upload sample reports (Excel/CSV). We will extract column metadata and build a field inventory.")

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
    # Show Uploaded Files
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
    # Build Field-Level Inventory
    # -------------------------------
    st.write("## Field Inventory (Raw)")
    field_rows = []

    for f in uploaded_files:
        try:
            if f.name.lower().endswith(".csv"):
                df = pd.read_csv(f)
                report_label = f.name
                for col in df.columns:
                    field_rows.append({
                        "report_name": report_label,
                        "column_original": str(col)
                    })
            else:
                xls = pd.ExcelFile(f)
                for sheet in xls.sheet_names:
                    df = xls.parse(sheet)
                    report_label = f"{f.name} | {sheet}"
                    for col in df.columns:
                        field_rows.append({
                            "report_name": report_label,
                            "column_original": str(col)
                        })
        except Exception as e:
            st.error(f"Could not process {f.name}: {e}")

    field_df = pd.DataFrame(field_rows)
    st.dataframe(field_df, use_container_width=True)

    # -------------------------------
    # Cross Tab (X / Blank)
    # -------------------------------
    if not field_df.empty:
        st.write("## Report vs Field Cross Tab (X = Present)")

        cross_tab = pd.crosstab(
            field_df["column_original"],
            field_df["report_name"]
        )

        cross_tab = cross_tab.applymap(lambda v: "X" if v > 0 else "")

        st.dataframe(cross_tab, use_container_width=True)
