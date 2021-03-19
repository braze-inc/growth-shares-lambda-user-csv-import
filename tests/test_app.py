import pytest

from braze_user_csv_import import app


def test_successful_import_offset_progresses(mocker, users, csv_processor):
    mocker.patch('braze_user_csv_import.app._post_users', return_value=75)
    chunks = [users] * 5
    csv_processor.processing_offset = 100

    assert csv_processor.total_offset == 0
    csv_processor.post_users(chunks)
    assert csv_processor.total_offset == 100


def test_failed_import_offset_does_not_progress(mocker, users, csv_processor):
    mocker.patch('braze_user_csv_import.app._post_users',
                 side_effect=RuntimeError)
    chunks = [users] * 5
    csv_processor.processing_offset = 100

    assert csv_processor.total_offset == 0
    with pytest.raises(RuntimeError):
        csv_processor.post_users(chunks)
    assert csv_processor.total_offset == 0


def test_posting_users_fails_one_some_users_assert_calls_not_repeated(mocker):
    pass


def test__handle_braze_response_success(mocker, users):
    mocker.patch('json.loads', return_value={"message": "success"})
    res = mocker.Mock(status_code=201)

    error_users = app._handle_braze_response(res)
    assert error_users == 0


def test__handle_braze_response_some_processed(mocker, users):
    res = mocker.Mock(status_code=201)
    mocker.patch('json.loads', return_value={
                 "errors": [{"there were some errors with index 1"}]})

    error_users = app._handle_braze_response(res)
    assert error_users == 1


def test__handle_braze_response_server_error_max_retries_not_reached_raises_non_fatal_api_error(mocker, users):
    res = mocker.Mock(status_code=429)
    mocker.patch('json.loads', return_value={"errors": {"too many requests"}})
    mocker.patch('braze_user_csv_import.app._delay', return_value=None)

    with pytest.raises(app.APIRetryError):
        app._handle_braze_response(res)


def test__handle_braze_response_server_error_max_retries_raises_fatal_api_error(mocker, users):
    res = mocker.Mock(status_code=500)
    mocker.patch('json.loads', return_value={
        "errors": {"some server errors"}})
    mocker.patch('braze_user_csv_import.app.RETRIES', app.MAX_API_RETRIES)

    with pytest.raises(app.FatalAPIError):
        app._handle_braze_response(res)
