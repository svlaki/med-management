from med_graph.sources.indication_match import (
    DISORDER_VOCAB,
    approved_disorders,
    positively_mentions,
)


class TestPositivelyMentions:
    def test_matches_a_plain_indication(self):
        assert positively_mentions(
            "Sertraline is indicated for major depressive disorder.",
            "major depressive disorder",
        )

    def test_absent_phrase_is_false(self):
        assert not positively_mentions("indicated for panic disorder", "schizophrenia")

    def test_skips_negated_mention(self):
        assert not positively_mentions(
            "X is not indicated for generalized anxiety disorder.",
            "generalized anxiety disorder",
        )

    def test_skips_limitations_of_use_mention(self):
        assert not positively_mentions(
            "Limitations of Use: not established in bipolar disorder.",
            "bipolar disorder",
        )

    def test_a_positive_occurrence_overrides_a_negated_one(self):
        text = (
            "Indicated for panic disorder. It is not indicated for panic disorder "
            "in pediatric patients."
        )
        assert positively_mentions(text, "panic disorder")

    def test_empty_text_is_false(self):
        assert not positively_mentions("", "panic disorder")
        assert not positively_mentions(None, "panic disorder")  # type: ignore[arg-type]


class TestApprovedDisorders:
    def test_extracts_all_matching_disorders_from_a_label(self):
        text = (
            "INDICATIONS AND USAGE Sertraline is indicated for major depressive "
            "disorder, obsessive-compulsive disorder, panic disorder, posttraumatic "
            "stress disorder, and social anxiety disorder."
        )
        got = set(approved_disorders(text))
        assert got == {
            "Major Depressive Disorder",
            "OCD",
            "Panic Disorder",
            "PTSD",
            "Social Anxiety Disorder",
        }
        assert "Generalized Anxiety Disorder" not in got

    def test_synonym_spelling_variants_match(self):
        assert "PTSD" in approved_disorders("indicated for post-traumatic stress disorder")
        assert "OCD" in approved_disorders("indicated for obsessive compulsive disorder")

    def test_expanded_vocabulary_matches(self):
        assert "Premenstrual Dysphoric Disorder" in approved_disorders(
            "Sertraline is indicated for premenstrual dysphoric disorder (PMDD)."
        )
        assert "Binge Eating Disorder" in approved_disorders(
            "indicated for the treatment of moderate to severe binge eating disorder"
        )
        assert "Bulimia Nervosa" in approved_disorders("indicated for bulimia nervosa")

    def test_legacy_depression_phrasing(self):
        """Older tricyclic / MAOI labels say 'depression' without 'MDD'."""
        assert "Major Depressive Disorder" in approved_disorders(
            "For the relief of symptoms of depression."
        )
        assert "Major Depressive Disorder" in approved_disorders(
            "indicated for the treatment of depression."
        )
        assert "Major Depressive Disorder" in approved_disorders(
            "indicated for the treatment of symptoms of mental depression."
        )
        assert "Major Depressive Disorder" in approved_disorders(
            "effective in depressed patients clinically characterized as atypical."
        )

    def test_legacy_anxiety_phrasing(self):
        """Older benzodiazepine labels say 'anxiety disorders' without 'GAD'."""
        assert "Generalized Anxiety Disorder" in approved_disorders(
            "indicated for the management of anxiety disorders."
        )
        assert "Generalized Anxiety Disorder" in approved_disorders(
            "for the short-term relief of the symptoms of anxiety."
        )
        assert "Generalized Anxiety Disorder" in approved_disorders(
            "For symptomatic relief of anxiety and tension."
        )

    def test_anxiety_in_descriptive_context_does_not_match_gad(self):
        """'symptoms of anxiety' in a comorbidity description is not an indication."""
        assert "Generalized Anxiety Disorder" not in approved_disorders(
            "patients had symptoms that corresponded to the DSM-IV category of "
            "major depressive disorder; however, they often also had signs and "
            "symptoms of anxiety."
        )

    def test_schizophrenia_adjective_forms(self):
        """Older labels use 'schizophrenic patients' or 'chronic schizophrenics'."""
        assert "Schizophrenia" in approved_disorders(
            "indicated for the management of schizophrenic patients."
        )
        assert "Schizophrenia" in approved_disorders(
            "intended for use in the management of chronic schizophrenics."
        )

    def test_schizophrenia_bullet_list(self):
        """Modern labels list indications as bullets."""
        assert "Schizophrenia" in approved_disorders(
            "indicated for: \u2022 Schizophrenia \u2022 Bipolar I disorder"
        )

    def test_schizophrenia_in_exclusion_does_not_match(self):
        """Schizophrenia named as a differential exclusion is not an indication."""
        assert "Schizophrenia" not in approved_disorders(
            "The above symptoms would not be due to another mental disorder, "
            "such as a depressive disorder or schizophrenia."
        )

    def test_insomnia_requires_indication_context(self):
        """Bare 'insomnia' in a symptom list should not match."""
        assert "Insomnia" not in approved_disorders(
            "manifested by symptoms including insomnia, psychomotor agitation."
        )
        assert "Insomnia" in approved_disorders(
            "indicated for the treatment of insomnia."
        )

    def test_new_disorder_categories(self):
        assert "Postpartum Depression" in approved_disorders(
            "indicated for the treatment of postpartum depression (PPD)."
        )
        assert "Seasonal Affective Disorder" in approved_disorders(
            "prevention of seasonal affective disorder (SAD)."
        )
        assert "Schizoaffective Disorder" in approved_disorders(
            "treatment of schizoaffective disorder."
        )
        assert "Psychotic Disorders" in approved_disorders(
            "For the management of manifestations of psychotic disorders."
        )

    def test_bipolar_manic_depressive_legacy(self):
        assert "Bipolar Disorder" in approved_disorders(
            "To control the manifestations of the manic type of "
            "manic-depressive illness."
        )

    def test_no_disorders_for_unrelated_text(self):
        assert approved_disorders("indicated for hypertension") == []

    def test_vocab_display_names_are_unique(self):
        names = list(DISORDER_VOCAB)
        assert len(names) == len(set(names))
