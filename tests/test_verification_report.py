from scripts.verify_integration import summarize


def test_failed_and_rejected_images_are_not_counted_as_successful_http_200():
    calls = [{'path': '/api/visual-story/image', 'http_status': 200, 'seconds': i + 1,
              'response': {'status': status}}
             for i, status in enumerate(['generated', 'failed', 'rejected', 'mock'])]
    result = summarize(calls)
    assert result['http_errors'] == 0
    assert result['image_unavailable_rate'] == .75
    assert result['image_mean_seconds'] == 2.5
    assert result['image_max_seconds'] == 4
    assert result['image_status_counts'] == dict(generated=1, failed=1, rejected=1, mock=1)
    assert result['quality_review'] == 'manual_required'


def test_empty_run_does_not_report_zero_image_failure_rate():
    result = summarize([])
    assert result['image_unavailable_rate'] is None
    assert result['image_mean_seconds'] is None
