import json
import pytest
from requests.exceptions import RequestException

from braze_user_csv_import import app


def test_lambda_handler_fails_assert_event_logged(mocker, capsys):
    headers = ["header1", "header2"]
    offset = 7256
    event = {"Records": [
        {"s3": {"bucket": {"name": "test"}, "object": {"key": "test"}}}]}

    mock_processor = mocker.MagicMock(headers=headers, total_offset=offset,
                                      processed_users=999)
    # Set off fatal exception during file processing
    mock_processor.process_file.side_effect = app.FatalAPIError("Test error")
    mock_processor = mocker.patch("braze_user_csv_import.app.CsvProcessor",
                                  return_value=mock_processor)
    with pytest.raises(Exception):
        app.lambda_handler(event, None)

    # Confirm that event gets logged
    logs, _ = capsys.readouterr()
    new_event = json.dumps({**event, "offset": offset, "headers": headers})
    assert 'Encountered error "Test error"' in logs
    assert f"{new_event}" in logs


def test_successful_import_offset_progresses(mocker, users, csv_processor):
    mocker.patch("braze_user_csv_import.app._post_users", return_value=75)
    chunks = [users] * 5
    csv_processor.processing_offset = 100

    assert csv_processor.total_offset == 0
    csv_processor.post_users(chunks)
    assert csv_processor.total_offset == 100


def test_failed_import_offset_does_not_progress(mocker, users, csv_processor):
    mocker.patch("braze_user_csv_import.app._post_users",
                 side_effect=RuntimeError)
    chunks = [users] * 5
    csv_processor.processing_offset = 100

    assert csv_processor.total_offset == 0
    with pytest.raises(RuntimeError):
        csv_processor.post_users(chunks)
    assert csv_processor.total_offset == 0


def test__process_row_empty_string_should_ignore():
    row = {"external_id": "user1", "attribute1": "", "attribute2": "value"}
    processed_row = app._process_row(row, {})
    assert len(processed_row) == 2
    assert "attribute1" not in processed_row


def test__process_row_null_string_should_convert_to_none():
    row = {"external_id": "user1", "attribute1": "null"}
    processed_row = app._process_row(row, {})
    assert len(processed_row) == 2
    assert processed_row["attribute1"] == None


def test__process_row_single_digit_value():
    row = {"external_id": "0166ecc9-asd9-0305-sjn9-efd44fe61b96", "attribute": "0"}
    processed_row = app._process_row(row, {})
    assert len(processed_row) > 1


def test__process_value_int():
    assert 90 == app._process_value("90")
    assert 0 == app._process_value("0")
    assert -5 == app._process_value("-5")


def test__process_value_float():
    assert 0.98 == app._process_value("0.98")
    assert -4.23 == app._process_value("-4.23")


def test__process_value_leading_zero_int():
    assert "0123" == app._process_value("0123")


def test__process_value_boolean():
    assert True == app._process_value("True")
    assert True == app._process_value("TRUE")
    assert False == app._process_value("false")


def test__process_value_array_of_numbers():
    assert [9.12, 1, 4] == app._process_value("[9.12, 1, 4]")


def test__process_value_array_of_strings():
    assert ["a", "b", "c"] == app._process_value("['a', 'b', 'c']")


def test__process_value_force_cast_to_int():
    assert 4 == app._process_value("4.23", int)
    assert 0 == app._process_value("00", int)


def test__process_value_force_cast_to_str():
    assert '2398' == app._process_value("2398", str)
    assert '4.123' == app._process_value("4.123", str)
    assert 'TRUE' == app._process_value("TRUE", str)


def test__process_value_force_cast_to_bool():
    assert False == app._process_value("False", bool)
    assert True == app._process_value("1", bool)
    assert False == app._process_value("0", bool)


def test__is_int():
    assert app._is_int("3")
    assert not app._is_int("4.23")


def test__process_list_string_should_deconstruct():
    row = {"external_id": "user1", "attribute1": "['value1', 'value2']"}
    processed_row = app._process_row(row, {})
    assert len(processed_row) == 2
    assert isinstance(processed_row["attribute1"], list)


def test__post_to_braze_api_retry_error_assert_fn_retried(mocker, users):
    app._post_to_braze.retry.sleep = mocker.Mock()
    mocker.patch("requests.post")
    handler_mock = mocker.patch("braze_user_csv_import.app._handle_braze_response",
                                side_effect=app.APIRetryError)

    with pytest.raises(Exception):
        app._post_to_braze(users)
    assert handler_mock.call_count == app.MAX_RETRIES


def test__post_to_braze_retry_connection_error_assert_fn_retried(mocker, users):
    app._post_to_braze.retry.sleep = mocker.Mock()
    request_mock = mocker.patch("requests.post", side_effect=RequestException)

    with pytest.raises(Exception):
        app._post_to_braze(users)
    assert request_mock.call_count == app.MAX_RETRIES


def test__post_to_braze_fatal_exception_not_retried(mocker, users):
    mocker.patch("requests.post")
    handler_mock = mocker.patch("braze_user_csv_import.app._handle_braze_response",
                                side_effect=app.FatalAPIError)

    with pytest.raises(Exception):
        app._post_to_braze(users)
    assert handler_mock.call_count == 1


def test__handle_braze_response_success(mocker):
    mocker.patch("json.loads", return_value={"message": "success"})
    res = mocker.Mock(status_code=201)

    error_users = app._handle_braze_response(res)
    assert error_users == 0


def test__handle_braze_response_some_processed(mocker):
    res = mocker.Mock(status_code=201)
    mocker.patch("json.loads", return_value={
                 "errors": [{"there were some errors with index 1"}]})

    error_users = app._handle_braze_response(res)
    assert error_users == 1


def test__handle_braze_response_server_error_max_retries_not_reached_raises_non_fatal_api_error(mocker):
    res = mocker.Mock(status_code=429)
    mocker.patch("json.loads", return_value={"errors": {"too many requests"}})

    with pytest.raises(app.APIRetryError):
        app._handle_braze_response(res)


def test__handle_braze_response_authorization_failure_raises_fatal_error(mocker):
    res = mocker.Mock(status_code=405)
    mocker.patch("json.loads", return_value={
        "errors": {"some server errors"}})

    with pytest.raises(app.FatalAPIError):
        app._handle_braze_response(res)


def test__process_type_cast_empty_string():
    assert not app._process_type_cast('')


def test_process_type_cast():
    cast = app._process_type_cast(
        'attr=string,numerical=integer, floaty=float')
    assert cast
    assert len(cast) == 3
    assert cast['attr'] == str
    assert cast['numerical'] == int
    assert cast['floaty'] == float


def test__process_type_cast_type_not_supported():
    cast = app._process_type_cast('attr=floaty')
    assert not cast
