from app.services.ats_scoring import JDTerms, compute_keyword_coverage, resume_content_to_text
from app.schemas.resume import ContactInfo, ExperienceEntry, ResumeContent, Skills


def test_term_present_does_not_false_positive_on_substring():
    resume = ResumeContent(
        contact=ContactInfo(name="Test"),
        skills=Skills(frameworks=["Django"]),
    )
    text = resume_content_to_text(resume)
    terms = JDTerms(must_have=["Go"], nice_to_have=[])

    keyword_score, present, missing, _, _ = compute_keyword_coverage(text, terms)

    assert present == []
    assert missing == ["Go"]
    # must_have coverage is 0.0; nice_to_have is empty so defaults to full coverage (1.0).
    assert keyword_score == round(0.3, 10)


def test_term_present_matches_whole_word_correctly():
    resume = ResumeContent(
        contact=ContactInfo(name="Test"),
        skills=Skills(languages=["Python"], frameworks=["Django"]),
    )
    text = resume_content_to_text(resume)
    terms = JDTerms(must_have=["Python", "Django"], nice_to_have=[])

    keyword_score, present, missing, _, _ = compute_keyword_coverage(text, terms)

    assert set(present) == {"Python", "Django"}
    assert missing == []
    assert keyword_score == 1.0


def test_compound_term_matches_via_any_subpart():
    resume = ResumeContent(
        contact=ContactInfo(name="Test"),
        skills=Skills(tools=["Docker"]),
    )
    text = resume_content_to_text(resume)
    terms = JDTerms(must_have=["Git, Linux, Docker, CI/CD pipelines"], nice_to_have=[])

    keyword_score, present, missing, _, _ = compute_keyword_coverage(text, terms)

    assert present == ["Git, Linux, Docker, CI/CD pipelines"]
    assert keyword_score == 1.0


def test_must_have_weighted_higher_than_nice_to_have():
    resume = ResumeContent(contact=ContactInfo(name="Test"), skills=Skills(languages=["Python"]))
    text = resume_content_to_text(resume)

    # All must-have present, no nice-to-have present.
    all_must = compute_keyword_coverage(text, JDTerms(must_have=["Python"], nice_to_have=["Kubernetes"]))[0]
    # No must-have present, all nice-to-have present.
    all_nice = compute_keyword_coverage(text, JDTerms(must_have=["Kubernetes"], nice_to_have=["Python"]))[0]

    assert all_must > all_nice


def test_empty_term_lists_default_to_full_coverage():
    text = resume_content_to_text(ResumeContent(contact=ContactInfo(name="Test")))
    keyword_score, present, missing, nice_present, nice_missing = compute_keyword_coverage(
        text, JDTerms(must_have=[], nice_to_have=[])
    )
    assert keyword_score == 1.0
    assert present == missing == nice_present == nice_missing == []


def test_resume_content_to_text_includes_key_sections():
    resume = ResumeContent(
        contact=ContactInfo(name="Jane Doe"),
        summary="A great engineer.",
        skills=Skills(languages=["Python"]),
        experience=[ExperienceEntry(company="Acme", title="Engineer", bullets=["Shipped a thing."])],
        certifications=["AWS Certified"],
    )
    text = resume_content_to_text(resume)

    assert "Jane Doe" in text
    assert "A great engineer." in text
    assert "Python" in text
    assert "Acme" in text
    assert "Shipped a thing." in text
    assert "AWS Certified" in text
