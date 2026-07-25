from app.services.autofill.detection import detect_ats_platform


def test_detects_greenhouse_boards_url():
    assert detect_ats_platform("https://boards.greenhouse.io/acme/jobs/12345") == "greenhouse"


def test_detects_greenhouse_job_boards_subdomain():
    assert detect_ats_platform("https://job-boards.greenhouse.io/acme/jobs/12345") == "greenhouse"


def test_unsupported_platforms_return_none():
    assert detect_ats_platform("https://jobs.lever.co/acme/12345") is None
    assert detect_ats_platform("https://example.com/careers/123") is None
    assert detect_ats_platform("https://notgreenhouse.io/acme/jobs/1") is None
