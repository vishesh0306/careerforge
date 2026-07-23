from app.models import JDAnalysis, JobListing, JobSearchPref, PipelineRun, Resume, User


def test_create_user(db_session):
    user = User(email="alice@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.flush()

    assert user.id is not None
    assert user.created_at is not None


def test_create_resume_with_jsonb(db_session):
    user = User(email="bob@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.flush()

    resume = Resume(
        user_id=user.id,
        structured_content={"contact": {"name": "Bob"}, "skills": {"languages": ["Python"]}},
        version=1,
    )
    db_session.add(resume)
    db_session.flush()
    db_session.expire(resume)

    fetched = db_session.get(Resume, resume.id)
    assert fetched.structured_content["contact"]["name"] == "Bob"
    assert fetched.structured_content["skills"]["languages"] == ["Python"]


def test_create_pipeline_run(db_session):
    user = User(email="carol@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.flush()

    run = PipelineRun(
        user_id=user.id,
        run_type="resume_builder",
        current_step="INTAKE",
        status="running",
        context={"messages": ["hi"]},
    )
    db_session.add(run)
    db_session.flush()

    assert run.id is not None
    assert run.context["messages"] == ["hi"]


def test_create_jd_analysis(db_session):
    user = User(email="dave@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.flush()

    resume = Resume(user_id=user.id, structured_content={}, version=1)
    db_session.add(resume)
    db_session.flush()

    analysis = JDAnalysis(
        resume_id=resume.id,
        jd_text="Need a backend engineer with AWS experience.",
        score=78.5,
        breakdown={"missing_must_have": ["AWS"]},
    )
    db_session.add(analysis)
    db_session.flush()

    assert analysis.id is not None
    assert analysis.breakdown["missing_must_have"] == ["AWS"]


def test_create_job_search_pref(db_session):
    user = User(email="erin@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.flush()

    pref = JobSearchPref(
        user_id=user.id,
        role="Backend Engineer",
        experience_years=1.5,
        location="Bangalore",
        job_type="full_time",
        work_mode="hybrid",
        expected_ctc="15-20 LPA",
    )
    db_session.add(pref)
    db_session.flush()

    assert pref.id is not None


def test_create_job_listing_and_unique_constraint(db_session):
    listing = JobListing(
        source="adzuna",
        external_id="xyz789",
        title="Backend Engineer",
        company="Acme Corp",
        jd_text="We need a backend engineer.",
        url="https://example.com/job/xyz789",
        location="Bangalore",
    )
    db_session.add(listing)
    db_session.flush()

    assert listing.id is not None
    assert listing.fetched_at is not None
