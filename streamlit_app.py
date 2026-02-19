import streamlit as st
import pandas as pd
import io
import re

# -------------------------------
# Helper: Flexible CSV Reader
# -------------------------------
def read_csv_flexible(uploaded_file):
    """
    Handles:
    - Normal CSV
    - CSV with BOM
    - CSV where each entire row is wrapped in quotes:
      "col1,col2,col3"
      "val1,val2,val3"
    """
    uploaded_file.seek(0)

    # Try normal read first
    try:
        df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
    except Exception:
        df = None

    # If only 1 column detected, likely wrapped-row CSV
    if df is None or df.shape[1] == 1:
        uploaded_file.seek(0)
        raw = uploaded_file.read()

        if isinstance(raw, bytes):
            text = raw.decode("utf-8-sig", errors="replace")
        else:
            text = raw

        fixed_lines = []
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
                line = line[1:-1]
            fixed_lines.append(line)

        fixed_text = "\n".join(fixed_lines)
        df = pd.read_csv(io.StringIO(fixed_text))

    return df


# -------------------------------
# Normalization
# -------------------------------
DEFAULT_SYNONYMS = {
    # policy
    "policy_no": "policy_number",
    "pol_no": "policy_number",
    "policyid": "policy_number",
    "policy_id": "policy_number",
    "policy#": "policy_number",
    "policynumber": "policy_number",
    "policy_number": "policy_number",

    # insured
    "insured_nm": "insured_name",
    "insuredname": "insured_name",
    "named_insured": "insured_name",
    "customer_name": "insured_name",

    # dates
    "eff_dt": "effective_date",
    "effective_dt": "effective_date",
    "term_effective_date": "effective_date",
    "exp_dt": "expiration_date",
    "expiry_date": "expiration_date",

    # premium
    "prem_amt": "premium_amount",
    "premium": "premium_amount",
    "written_premium": "premium_amount",
    "total_premium": "premium_amount",

    # deductible
    "ded_amt": "deductible_amount",
    "deductible": "deductible_amount",
    "deductible_amt": "deductible_amount",

    # claim
    "claimno": "claim_number",
    "claim_no": "claim_number",
    "claim#": "claim_number",

    # address
    "addr": "address",
    "street_addr": "address",
}

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to",
    "no", "num", "number",  # often redundant after mapping (policy_no -> policy_number)
}

def normalize_col_name(name: str, synonyms: dict, remove_stopwords: bool = False) -> str:
    """
    Normalizes a column name into a consistent snake_case key, then applies synonyms mapping.
    """
    if name is None:
        return ""
    s = str(name).strip().lower()

    # replace separators with spaces
    s = re.sub(r"[\t\r\n]+", " ", s)
    s = re.sub(r"[\/\-\.\,\:\;\|\(\)\[\]\{\}]+", " ", s)

    # keep alphanumerics and spaces only
    s = re.sub(r"[^a-z0-9\s#]+", " ", s)  # keep # for policy#/claim#
    s = s.replace("#", " # ")

    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    tokens = s.split(" ")
    if remove_stopwords:
        tokens = [t for t in tokens if t and t not in STOPWORDS]

    # snake_case
    key = "_".join([t for t in tokens if t])

    # cleanup underscores
    key = re.sub(r"_+", "_", key).strip("_")

    # apply synonyms (exact key match)
    return synonyms.get(key, key)


def parse_synonyms_from_text(text: str) -> dict:
    """
    Accepts lines like:
      policy no = policy_number
      PolNo -> policy_number
      policy# : policy_number
    Returns dict of normalized_left_key -> normalized_right_key
    """
    syn = {}
    if not text or not text.strip():
        return syn

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        # allow separators: =, ->, :, ,
        m = re.split(r"\s*(=|->|:)\s*", ln, maxsplit=1)
        if len(m) >= 3:
            left = m[0].strip()
            right = m[2].strip()
        else:
            # fallback: split on comma
            parts = [p.strip() for p in ln.split(",") if p.strip()]
            if len(parts) >= 2:
                left, right = parts[0], parts[1]
            else:
                continue

        # normalize both sides to internal keys
        left_key = normalize_col_name(left, {}, remove_stopwords=False)
        right_key = normalize_col_name(right, {}, remove_stopwords=False)
        if left_key and right_key:
            syn[left_key] = right_key
    return syn


# -------------------------------
# Page Config
# -------------------------------
st.set_page_config(page_title="Insurance Data Discovery", layout="wide")
st.title("Insurance Data Discovery Tool (Module 1)")
st.caption("Upload sample reports (Excel/CSV). We will extract column metadata, build a field inventory, and support normalization.")

# -------------------------------
# Inputs
# -------------------------------
source_system = st.text_input("Source System Name (e.g., Legacy PAS, Mainframe Claims)")

uploaded_files = st.file_uploader(
    "Upload report files",
    type=["xlsx", "csv"],
    accept_multiple_files=True
)

st.markdown("---")
st.subheader("Normalization (Optional)")
enable_norm = st.checkbox("Enable Normalization", value=True)

remove_stopwords = st.checkbox("Remove stopwords during normalization (more aggressive)", value=False)

custom_syn_text = st.text_area(
    "Custom synonym rules (one per line). Examples:\n"
    "Policy No = policy_number\n"
    "PolNo -> policy_number\n"
    "Claim# : claim_number\n",
    height=140
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

    # Build synonyms
    synonyms = dict(DEFAULT_SYNONYMS)
    synonyms.update(parse_synonyms_from_text(custom_syn_text))

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
                df = read_csv_flexible(f)
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
    # Build Field-Level Inventory (Raw + Normalized)
    # -------------------------------
    st.write("## Field Inventory (Raw" + (" + Normalized" if enable_norm else "") + ")")
    field_rows = []

    for f in uploaded_files:
        try:
            if f.name.lower().endswith(".csv"):
                df = read_csv_flexible(f)
                report_label = f.name
                for col in df.columns:
                    row = {
                        "report_name": report_label,
                        "column_original": str(col)
                    }
                    if enable_norm:
                        row["column_normalized"] = normalize_col_name(str(col), synonyms, remove_stopwords=remove_stopwords)
                    field_rows.append(row)
            else:
                xls = pd.ExcelFile(f)
                for sheet in xls.sheet_names:
                    df = xls.parse(sheet)
                    report_label = f"{f.name} | {sheet}"
                    for col in df.columns:
                        row = {
                            "report_name": report_label,
                            "column_original": str(col)
                        }
                        if enable_norm:
                            row["column_normalized"] = normalize_col_name(str(col), synonyms, remove_stopwords=remove_stopwords)
                        field_rows.append(row)
        except Exception as e:
            st.error(f"Could not process {f.name}: {e}")

    field_df = pd.DataFrame(field_rows)
    st.dataframe(field_df, use_container_width=True)

    # -------------------------------
    # Normalization Summary (optional)
    # -------------------------------
    if enable_norm and not field_df.empty:
        st.write("## Normalization Map (Unique)")
        norm_map = (
            field_df[["column_original", "column_normalized"]]
            .drop_duplicates()
            .sort_values(["column_normalized", "column_original"])
        )
        st.dataframe(norm_map, use_container_width=True)

        st.write("## Normalization Coverage")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Unique Original Columns", int(field_df["column_original"].nunique()))
        with c2:
            st.metric("Unique Normalized Columns", int(field_df["column_normalized"].nunique()))
        with c3:
            # how many originals collapsed into fewer normalized keys
            collapsed = int(field_df["column_original"].nunique() - field_df["column_normalized"].nunique())
            st.metric("Collapsed Count", collapsed)

    # -------------------------------
    # Cross Tab (X / Blank) + Totals Row + Repetition Count Column
    # -------------------------------
    if not field_df.empty:
        st.write("## Report vs Field Cross Tab (X = Present)" + (" — Normalized" if enable_norm else ""))

        row_field = "column_normalized" if enable_norm else "column_original"

        # Base crosstab (counts)
        cross_counts = pd.crosstab(
            field_df[row_field],
            field_df["report_name"]
        )

        # Convert to "x" / "" display
        cross_tab = cross_counts.applymap(lambda v: "x" if v > 0 else "")

        # Add "Repetition Count" column = number of "x" across report columns for each field
        cross_tab["Repetition Count"] = (cross_tab == "x").sum(axis=1)

        # Add "Totals" row = count of "x" down each report column
        totals = (cross_tab == "x").sum(axis=0)
        totals["Repetition Count"] = int(cross_tab["Repetition Count"].sum())
        cross_tab.loc["Totals"] = totals

        st.dataframe(cross_tab, use_container_width=True)
