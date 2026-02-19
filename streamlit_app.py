import streamlit as st
import pandas as pd

st.set_page_config(page_title="Insurance Data Discovery", layout="wide")

st.title("Insurance Data Discovery Tool (Module 1)")
st.caption("Upload sample reports (Excel/CSV). We will extract column metadata and build a field inventory.")

# Inputs
source_system = st.text_input("Source System Name (e.g., Legacy PAS, Mainframe Claims)")

uploaded_files = st.file_uploader(
    "Upload report files",
    type=["xlsx", "csv"],
    accept_multiple_files=True
)

col1, col2 = st.columns([1, 2])

with col1:
    analyze = st.button("Analyze Reports", type="primary", use_container_width=True)

with col2:
    st.info("Tip: Start with 2–3 reports. We'll add Excel output generation next.", icon="ℹ️")

if analyze:
    if not uploaded_files:
        st.warning("Please upload at least one Excel or CSV report.")
        st.stop()

    if not source_system.strip():
        st.warning("Please enter a Source System Name.")
        st.stop()

    st.success(f"Uploaded {len(uploaded_files)} file(s) for Source System: {source_system}")

    st.write("## Uploaded Files")
    for f in uploaded_files:
        st.write(f"• {f.name}")

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
                for sheet in xls.sheet_names[:10]:  # safety limit
                    df = xls.parse(sheet)
                    profile_rows.append({
                        "file_name": f.name,
                        "sheet_name": sheet,
                        "rows": len(df),
                        "columns": len(df.columns),
                        "sample_columns": ", ".join([str(c) for c in df.columns[:10]])
                    })
        except Exception as e:
            profile_rows.append({
                "file_name": f.name,
                "sheet_name": "(error)",
                "rows": "",
                "columns": "",
                "sample_columns": f"Could not read file: {e}"
            })

    st.dataframe(pd.DataFrame(profile_rows), use_container_width=True)
