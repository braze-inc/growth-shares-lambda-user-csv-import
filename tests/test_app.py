import json
import os
import pytest
from requests.exceptions import RequestException

from braze_user_csv_import.braze_attributes import (
    is_int,
    process_row,
    process_type_cast,
    process_value,
)
from braze_user_csv_import.braze_client import handle_braze_response, post_to_braze
from braze_user_csv_import.constants import MAX_RETRIES
from braze_user_csv_import.errors import APIRetryError, FatalAPIError
from braze_user_csv_import.handler import lambda_handler


def test_lambda_handler_fails_assert_event_logged(mocker, lambda_event, capsys):
    headers = ["header1", "header2"]
    offset = 7256
    mock_processor = mocker.MagicMock(headers=headers, total_offset=offset,
                                      processed_users=999)
    # Set off fatal exception during file processing
    mock_processor.process_file.side_effect = FatalAPIError("Test error")
    mocker.patch("braze_user_csv_import.handler.CsvProcessor",
                 return_value=mock_processor)

    with pytest.raises(Exception):
        lambda_handler(lambda_event, None)

    # Confirm that event gets logged
    logs, _ = capsys.readouterr()
    new_event = json.dumps({
        **lambda_event,
        "offset": offset,
        "headers": headers
    })
    assert 'Encountered error: "Test error"' in logs
    assert f"{new_event}" in logs


def test_success_message_published_after_processing(mocker, lambda_event, mock_csv_processor):
    target_arn = "arn::target_arn"
    mock_boto3 = mocker.patch("braze_user_csv_import.handler.boto3.client")
    mocker.patch.dict(os.environ, {"TOPIC_ARN": target_arn})
    mocker.patch("braze_user_csv_import.handler.CsvProcessor",
                 return_value=mock_csv_processor)

    lambda_handler(lambda_event, None)
    mock_boto3.assert_called_with('sns')
    assert mock_boto3.return_value.publish.called


def test_fail_message_published_after_error(mocker, lambda_event, mock_csv_processor):
    target_arn = "arn::target_arn"
    mock_boto3 = mocker.patch("braze_user_csv_import.handler.boto3.client")
    mocker.patch.dict(os.environ, {"TOPIC_ARN": target_arn})
    mock_csv_processor.process_file.side_effect = FatalAPIError(
        "Test error")
    mocker.patch("braze_user_csv_import.handler.CsvProcessor",
                 return_value=mock_csv_processor)

    with pytest.raises(Exception):
        lambda_handler(lambda_event, None)

    mock_boto3.assert_called_with('sns')
    assert mock_boto3.return_value.publish.called


def test_no_message_published_without_topic(mocker, lambda_event, mock_csv_processor):
    mock_boto3 = mocker.patch("braze_user_csv_import.handler.boto3.client")
    mocker.patch("braze_user_csv_import.handler.CsvProcessor",
                 return_value=mock_csv_processor)
    lambda_handler(lambda_event, None)
    assert not mock_boto3.called


def test_successful_import_offset_progresses(mocker, users, csv_processor):
    mocker.patch("braze_user_csv_import.csv_processor.post_user_chunks", return_value=75)
    chunks = [users] * 5
    csv_processor.processing_offset = 100

    assert csv_processor.total_offset == 0
    csv_processor.post_users(chunks)
    assert csv_processor.total_offset == 100


def test_failed_import_offset_does_not_progress(mocker, users, csv_processor):
    mocker.patch("braze_user_csv_import.csv_processor.post_user_chunks",
                 side_effect=RuntimeError)
    chunks = [users] * 5
    csv_processor.processing_offset = 100

    assert csv_processor.total_offset == 0
    with pytest.raises(RuntimeError):
        csv_processor.post_users(chunks)
    assert csv_processor.total_offset == 0


def test__process_row_empty_string_should_ignore():
    row = {"external_id": "user1", "attribute1": "", "attribute2": "value"}
    processed_row = process_row(row, {})
    assert len(processed_row) == 2
    assert "attribute1" not in processed_row


def test__process_row_null_string_should_convert_to_none():
    row = {"external_id": "user1", "attribute1": "null"}
    processed_row = process_row(row, {})
    assert len(processed_row) == 2
    assert processed_row["attribute1"] == None


def test__process_row_single_digit_value():
    row = {"external_id": "0166ecc9-asd9-0305-sjn9-efd44fe61b96", "attribute": "0"}
    processed_row = process_row(row, {})
    assert len(processed_row) > 1


def test__process_value_numerical():
    assert 90 == process_value("90")
    assert 0 == process_value("0")
    assert -5 == process_value("-5")

    assert 0.98 == process_value("0.98")
    assert -4.23 == process_value("-4.23")
    assert "972-000-0000" == process_value("972-000-0000")
    assert "11/11/2011" == process_value("11/11/2011")


def test__process_value_leading_zero_int():
    assert "0123" == process_value("0123")


def test__process_value_boolean():
    assert True == process_value("True")
    assert True == process_value("TRUE")
    assert False == process_value("false")


def test__process_value_null():
    assert None == process_value("null")


def test__process_value_array():
    assert [9.12, 1, 4] == process_value("[9.12, 1, 4]")
    assert ["a", "b", "c"] == process_value("['a', 'b', 'c']")
    assert process_value("[ab-cd]") == "[ab-cd]"


def test__process_value_starts_with_symbol():
    assert "[ex" == process_value("[ex")
    assert "<lol" == process_value("<lol")
    assert "str[he%l@@]" == process_value("str[he%l@@]")


def test__process_value_nan_string():
    assert 'nan' == process_value("nan")


def test__process_value_force_cast_to_int():
    assert 4 == process_value("4.23", int)
    assert 0 == process_value("00", int)
    assert -230 == process_value("-230", int)


def test__process_value_force_cast_to_str():
    assert '2398' == process_value("2398", str)
    assert '4.123' == process_value("4.123", str)
    assert 'TRUE' == process_value("TRUE", str)


def test__process_value_force_cast_to_bool():
    assert False == process_value("False", bool)
    assert True == process_value("1", bool)
    assert False == process_value("0", bool)


def test__is_int():
    assert is_int("3")
    assert not is_int("4.23")


def test__process_list_string_should_deconstruct():
    row = {"external_id": "user1", "attribute1": "['value1', 'value2']"}
    processed_row = process_row(row, {})
    assert len(processed_row) == 2
    assert isinstance(processed_row["attribute1"], list)


def test__post_to_braze_api_retry_error_assert_fn_retried(mocker, users):
    post_to_braze.retry.sleep = mocker.Mock()
    mocker.patch("requests.post")
    handler_mock = mocker.patch("braze_user_csv_import.braze_client.handle_braze_response",
                                side_effect=APIRetryError)

    with pytest.raises(Exception):
        post_to_braze(users)
    assert handler_mock.call_count == MAX_RETRIES


def test__post_to_braze_retry_connection_error_assert_fn_retried(mocker, users):
    post_to_braze.retry.sleep = mocker.Mock()
    request_mock = mocker.patch("requests.post", side_effect=RequestException)

    with pytest.raises(Exception):
        post_to_braze(users)
    assert request_mock.call_count == MAX_RETRIES


def test__post_to_braze_fatal_exception_not_retried(mocker, users):
    mocker.patch("requests.post")
    handler_mock = mocker.patch("braze_user_csv_import.braze_client.handle_braze_response",
                                side_effect=FatalAPIError)

    with pytest.raises(Exception):
        post_to_braze(users)
    assert handler_mock.call_count == 1


def test__handle_braze_response_success(mocker):
    mocker.patch("json.loads", return_value={"message": "success"})
    res = mocker.Mock(status_code=201)

    error_users = handle_braze_response(res)
    assert error_users == 0


def test__handle_braze_response_some_processed(mocker):
    res = mocker.Mock(status_code=201)
    mocker.patch("json.loads", return_value={
                 "errors": [{"there were some errors with index 1"}]})

    error_users = handle_braze_response(res)
    assert error_users == 1


def test__handle_braze_response_server_error_max_retries_not_reached_raises_non_fatal_api_error(mocker):
    res = mocker.Mock(status_code=429)
    mocker.patch("json.loads", return_value={
                 "errors": {"too many requests"}})

    with pytest.raises(APIRetryError):
        handle_braze_response(res)


def test__handle_braze_response_authorization_failure_raises_fatal_error(mocker):
    res = mocker.Mock(status_code=405)
    mocker.patch("json.loads", return_value={
        "errors": {"some server errors"}})

    with pytest.raises(FatalAPIError):
        handle_braze_response(res)


def test__process_type_cast_empty_string():
    assert not process_type_cast('')


def test_process_type_cast():
    cast = process_type_cast(
        'attr=string,numerical=integer, floaty=float')
    assert cast
    assert len(cast) == 3
    assert cast['attr'] == str
    assert cast['numerical'] == int
    assert cast['floaty'] == float


def test__process_type_cast_type_not_supported():
    cast = process_type_cast('attr=floaty')
    assert not cast


def test_unfinished_file_invokes_next_lambda(mocker, lambda_event, mock_csv_processor):
    mock_csv_processor.is_finished.return_value = False
    mock_boto3 = mocker.patch("braze_user_csv_import.handler.boto3.client")
    mocker.patch("braze_user_csv_import.handler.CsvProcessor",
                 return_value=mock_csv_processor)
    context = mocker.Mock()
    context.function_name = "braze-user-csv-import"

    lambda_handler(lambda_event, context)

    mock_boto3.assert_any_call("lambda")
    invoke_kwargs = mock_boto3.return_value.invoke.call_args.kwargs
    assert invoke_kwargs["FunctionName"] == "braze-user-csv-import"
    assert invoke_kwargs["InvocationType"] == "Event"
    payload = json.loads(invoke_kwargs["Payload"])
    assert payload["offset"] == mock_csv_processor.total_offset
    assert payload["headers"] == mock_csv_processor.headers
