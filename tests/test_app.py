import pytest

from braze_user_csv_import import app


def test__handle_braze_response_success(mocker, users):
    res = mocker.Mock(status_code=201)
    mocker.patch('json.loads', return_value={"message": "success"})
    users_processed = app._handle_braze_response(res, users)
    assert users_processed == len(users)


def test__handle_braze_response_half_processed(mocker, users):
    res = mocker.Mock(status_code=201)
    mocker.patch('json.loads', return_value={
                 "errors": [{"there were some errors with index 1"}]})
    users_processed = app._handle_braze_response(res, users)
    assert users_processed == len(users) - 1


def test__handle_braze_response_server_error_max_retries_not_reached(mocker, users):
    res = mocker.Mock(status_code=429)
    mocker.patch('json.loads', return_value={"errors": {"too many requests"}})
    mocker.patch('braze_user_csv_import.app._wait', return_value=None)
    users_processed = app._handle_braze_response(res, users)
    assert users_processed == 0


def test__handle_braze_response_server_error_max_retries_raises_run_time_error(mocker, users):
    res = mocker.Mock(status_code=503)
    mocker.patch('json.loads', return_value={
        "errors": {"some server errors"}})
    mocker.patch('braze_user_csv_import.app.RETRIES', 5)
    with pytest.raises(RuntimeError):
        app._handle_braze_response(res, users)
