from app.chat.few_shot import classify_query, get_few_shot_examples, format_few_shot_block


class TestClassifyQuery:
    def test_factual_de(self):
        assert classify_query("Wie viele ECTS hat die Masterarbeit?") == "factual"

    def test_factual_semester(self):
        assert classify_query("Wie lang ist die Regelstudienzeit?") == "factual"

    def test_process_de(self):
        assert classify_query("Wie melde ich mich zur Masterarbeit an?") == "process"

    def test_process_en(self):
        assert classify_query("How do I register for the thesis?") == "process"

    def test_comparison(self):
        assert classify_query("Was ist der Unterschied zwischen Pflicht- und Wahlpflichtmodulen?") == "comparison"

    def test_amendment(self):
        assert classify_query("Was hat sich 2024 geändert?") == "amendment"

    def test_eligibility_de(self):
        assert classify_query("Welche Voraussetzungen brauche ich?") == "eligibility"

    def test_eligibility_en(self):
        assert classify_query("What are the admission requirements?") == "eligibility"

    def test_unknown_defaults_to_factual(self):
        assert classify_query("Hallo") == "factual"

    def test_amendment_and_eligibility_returns_factual(self):
        # "Eignungssatzung geändert?" matches both — should not restrict to either doc_type
        assert classify_query("Wurde die Eignungssatzung geändert?") == "factual"

    def test_amendment_alone(self):
        assert classify_query("Was hat sich 2024 geändert?") == "amendment"

    def test_eligibility_alone(self):
        assert classify_query("Welche Zugangsvoraussetzungen gibt es?") == "eligibility"


class TestGetFewShotExamples:
    def test_returns_list(self):
        examples = get_few_shot_examples("Wie viele ECTS?")
        assert isinstance(examples, list)
        assert len(examples) <= 2

    def test_max_examples(self):
        examples = get_few_shot_examples("Wie melde ich mich an?", max_examples=1)
        assert len(examples) == 1

    def test_examples_have_q_and_a(self):
        examples = get_few_shot_examples("Was ist der Unterschied?")
        for ex in examples:
            assert "q" in ex
            assert "a" in ex


class TestGetFewShotExamplesEnglish:
    def test_returns_english_examples(self):
        examples = get_few_shot_examples("How many ECTS?", lang="en")
        assert isinstance(examples, list)
        assert len(examples) > 0
        assert any("ECTS" in ex["q"] for ex in examples)

    def test_english_examples_contain_german_terms(self):
        examples = get_few_shot_examples("How do I register?", lang="en")
        combined = " ".join(ex["a"] for ex in examples)
        assert "(" in combined

    def test_default_is_german(self):
        examples_de = get_few_shot_examples("Wie viele ECTS?")
        examples_en = get_few_shot_examples("Wie viele ECTS?", lang="en")
        assert examples_de[0]["q"] != examples_en[0]["q"]


class TestFormatFewShotBlock:
    def test_empty(self):
        assert format_few_shot_block([]) == ""

    def test_format(self):
        block = format_few_shot_block([{"q": "Test?", "a": "Answer."}])
        assert "**Frage:**" in block
        assert "**Antwort:**" in block
        assert "Test?" in block

    def test_english_labels(self):
        block = format_few_shot_block([{"q": "Test?", "a": "Answer."}], lang="en")
        assert "**Question:**" in block
        assert "**Answer:**" in block
        assert "**Frage:**" not in block
