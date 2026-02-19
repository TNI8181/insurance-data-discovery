    # --------------------------------------
    # Merge definitions into field_df
    # --------------------------------------
    field_df = field_df.merge(
        edited_definitions[[
            "column_homogenized",
            "include_flag",
            "business_definition"
        ]],
        on="column_homogenized",
        how="left"
    )

    # --------------------------------------
    # Create Tabs
    # --------------------------------------
    tab1, tab2, tab3 = st.tabs(["Discovery", "Cross Tabs", "Homogenisation Report"])

    # --------------------------------------
    # TAB 1 — DISCOVERY
    # --------------------------------------
    with tab1:
        st.write("## Quick Profiling (Preview)")
        st.dataframe(profile_df, use_container_width=True)

        st.write("## Field Inventory (Raw + Normalised + Homogenised)")
        st.dataframe(field_df, use_container_width=True)

        st.write("## Business Definitions (Applied)")
        st.dataframe(edited_definitions, use_container_width=True)

        # Summary Metrics
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

    # --------------------------------------
    # TAB 2 — CROSS TABS
    # --------------------------------------
    with tab2:
        st.write("### Cross Tab (Original Column Names)")
        ct_orig = pd.crosstab(field_df["column_original"], field_df["report_name"])
        ct_orig = ct_orig.applymap(lambda v: "X" if v > 0 else "")
        st.dataframe(ct_orig, use_container_width=True)

        st.write("### Cross Tab (Homogenized Column Names)")
        ct_homo = pd.crosstab(field_df["column_homogenized"], field_df["report_name"])
        ct_homo = ct_homo.applymap(lambda v: "X" if v > 0 else "")
        st.dataframe(ct_homo, use_container_width=True)

        st.write("### Report Rationalisation")
        rational_df = build_report_rationalization(field_df)
        st.caption("High overlap + low uniqueness ⇒ possibly redundant")
        st.dataframe(rational_df, use_container_width=True)

    # --------------------------------------
    # TAB 3 — HOMOGENISATION REPORT
    # --------------------------------------
    with tab3:
        st.header("Homogenisation Report")

        # A) Transformation Journey
        st.subheader("A) Transformation Journey (Original → Normalised → Base → Final)")
        transform_df = field_df[[
            "report_name",
            "column_original",
            "column_normalized",
            "column_homogenized"
        ]].copy()
        transform_df["column_base_homogenized"] = transform_df["column_normalized"].apply(base_homogenize)
        st.dataframe(transform_df, use_container_width=True)

        # B) Collapse Summary
        st.subheader("B) Collapse Summary (Variants → Homogenised Field)")
        collapse_df = (
            field_df.groupby("column_homogenized")["column_original"]
            .unique()
            .reset_index()
            .rename(columns={"column_original": "source_variants"})
        )
        collapse_df["variant_count"] = collapse_df["source_variants"].apply(len)
        st.dataframe(collapse_df, use_container_width=True)

        # C) Unmatched Fields
        st.subheader("C) Fields Not Homogenised (Require Rule Review)")
        unmatched_df = transform_df[
            transform_df["column_normalized"] == transform_df["column_homogenized"]
        ]
        st.dataframe(unmatched_df, use_container_width=True)

        # D) Synonym Rule Effectiveness
        st.subheader("D) Synonym Rule Effectiveness")
        syn_eff_rows = []
        for _, row in st.session_state["synonyms_df"].iterrows():
            pattern = row["pattern"]
            replacement = row["replacement"]
            enabled = row["enabled"]
            matched = transform_df["column_base_homogenized"].str.contains(pattern, regex=True).sum() if enabled == "Y" else 0

            syn_eff_rows.append({
                "pattern": pattern,
                "replacement": replacement,
                "enabled": enabled,
                "matched_fields": matched
            })

        syn_eff_df = pd.DataFrame(syn_eff_rows)
        st.dataframe(syn_eff_df, use_container_width=True)

        # E) Confidence Score
        st.subheader("E) Confidence Score")
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

    # --------------------------------------
    # DOWNLOAD OUTPUT
    # --------------------------------------
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
        "__Report_Rationalization": rational_df,
        "__Homogenisation_Transform": transform_df,
        "__Homogenisation_Collapse": collapse_df,
        "__Homogenisation_Unmatched": unmatched_df,
        "__Homogenisation_Rule_Effectiveness": syn_eff_df,
        "__Homogenisation_Confidence": conf_df
    })

    st.download_button(
        label="Download Excel Output",
        data=excel_bytes,
        file_name=f"data_discovery_output_{source_system.strip().replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
