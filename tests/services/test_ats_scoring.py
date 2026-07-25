from unittest.mock import patch

import pytest

from app.services.ats_scoring import (
    JDTerms,
    compute_experience_fit,
    compute_keyword_coverage,
    resume_content_to_text,
    score_resume_against_jd,
)
from app.schemas.resume import ContactInfo, ExperienceEntry, ProjectEntry, ResumeContent, Skills


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


def test_resume_content_to_text_includes_skills_other_and_achievements_and_project_bullets():
    resume = ResumeContent(
        contact=ContactInfo(name="Jane Doe"),
        skills=Skills(other=["MySQL", "Design Patterns"]),
        projects=[ProjectEntry(name="Widget", bullets=["Built the thing.", "Scaled the thing."])],
        achievements=["Winner, Some Hackathon"],
    )
    text = resume_content_to_text(resume)

    assert "MySQL" in text
    assert "Design Patterns" in text
    assert "Built the thing." in text
    assert "Scaled the thing." in text
    assert "Winner, Some Hackathon" in text


def test_compute_experience_fit_full_credit_when_no_requirement_stated():
    assert compute_experience_fit(candidate_years=0.5, min_years_required=None) == 1.0
    assert compute_experience_fit(candidate_years=0.5, min_years_required=0) == 1.0


def test_compute_experience_fit_full_credit_when_candidate_meets_or_exceeds():
    assert compute_experience_fit(candidate_years=3.0, min_years_required=3.0) == 1.0
    assert compute_experience_fit(candidate_years=5.0, min_years_required=3.0) == 1.0


def test_compute_experience_fit_partial_credit_when_under_requirement():
    assert compute_experience_fit(candidate_years=1.0, min_years_required=3.0) == pytest.approx(1 / 3)


def test_compute_experience_fit_zero_when_no_experience_but_requirement_exists():
    assert compute_experience_fit(candidate_years=0.0, min_years_required=3.0) == 0.0


def test_score_resume_against_jd_skips_llm_call_when_candidate_years_precomputed():
    resume = ResumeContent(
        contact=ContactInfo(name="Test"),
        experience=[ExperienceEntry(company="Acme", title="Engineer", start_date="2020", end_date="Present")],
    )
    terms = JDTerms(must_have=["Python"], nice_to_have=[], min_years_required=3.0)

    with (
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.8),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Great fit."),
        patch("app.services.ats_scoring.extract_candidate_years_experience") as mock_extract,
    ):
        result = score_resume_against_jd(resume, "Need Python, 3+ years.", candidate_years_experience=5.0)

    mock_extract.assert_not_called()
    assert result.candidate_years_experience == 5.0


def test_score_resume_against_jd_computes_candidate_years_when_not_provided():
    resume = ResumeContent(
        contact=ContactInfo(name="Test"),
        experience=[ExperienceEntry(company="Acme", title="Engineer", start_date="2020", end_date="Present")],
    )
    terms = JDTerms(must_have=["Python"], nice_to_have=[], min_years_required=3.0)

    with (
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.8),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Great fit."),
        patch("app.services.ats_scoring.extract_candidate_years_experience", return_value=4.0) as mock_extract,
    ):
        result = score_resume_against_jd(resume, "Need Python, 3+ years.")

    mock_extract.assert_called_once()
    assert result.candidate_years_experience == 4.0


def test_score_resume_against_jd_skips_extraction_when_jd_terms_precomputed():
    resume = ResumeContent(contact=ContactInfo(name="Test"), skills=Skills(languages=["Python"]))
    precomputed_terms = JDTerms(must_have=["Python", "Django"], nice_to_have=["Docker"], min_years_required=3.0)

    with (
        patch("app.services.ats_scoring.extract_jd_terms") as mock_extract_terms,
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.8),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Great fit."),
        patch("app.services.ats_scoring.extract_candidate_years_experience", return_value=5.0),
    ):
        result = score_resume_against_jd(resume, "irrelevant jd text", jd_terms=precomputed_terms)

    mock_extract_terms.assert_not_called()
    assert result.must_have_present == ["Python"]
    assert result.must_have_missing == ["Django"]
    assert result.min_years_required == 3.0


def test_score_resume_against_jd_extracts_jd_terms_when_not_provided():
    resume = ResumeContent(contact=ContactInfo(name="Test"), skills=Skills(languages=["Python"]))
    terms = JDTerms(must_have=["Python"], nice_to_have=[], min_years_required=3.0)

    with (
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms) as mock_extract_terms,
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.8),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Great fit."),
        patch("app.services.ats_scoring.extract_candidate_years_experience", return_value=5.0),
    ):
        score_resume_against_jd(resume, "Need Python, 3+ years.")

    mock_extract_terms.assert_called_once()
