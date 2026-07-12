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

    def test_no_disorders_for_unrelated_text(self):
        assert approved_disorders("indicated for hypertension") == []

    def test_vocab_display_names_are_unique(self):
        names = list(DISORDER_VOCAB)
        assert len(names) == len(set(names))
