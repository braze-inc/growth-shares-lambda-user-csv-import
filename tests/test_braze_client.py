import json

from braze_user_csv_import.braze_client import BrazeClient


def test_track_attributes_posts_users_track_body(mocker):
    response = mocker.Mock(status_code=201, text='{"message": "success"}')
    post = mocker.patch(
        "braze_user_csv_import.braze_client.requests.post",
        return_value=response,
    )
    client = BrazeClient(api_url="https://rest.iad-01.braze.com/", api_key="secret")

    accepted = client.track_attributes([
        {"external_id": "abc123", "loyalty_point": 1982}
    ])

    assert accepted == 1
    assert post.call_args.args[0] == "https://rest.iad-01.braze.com/users/track"
    headers = post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Braze-Bulk"] == "true"
    assert json.loads(post.call_args.kwargs["data"]) == {
        "attributes": [{"external_id": "abc123", "loyalty_point": 1982}]
    }


def test_track_objects_posts_events_array(mocker):
    response = mocker.Mock(status_code=201, text='{"message": "success"}')
    post = mocker.patch(
        "braze_user_csv_import.braze_client.requests.post",
        return_value=response,
    )
    client = BrazeClient(api_url="https://rest.iad-01.braze.com", api_key="secret")

    accepted = client.track_objects(
        [{
            "external_id": "user1",
            "name": "rented_movie",
            "time": "2013-07-16T19:20:45+01:00",
        }],
        object_type="events",
    )

    assert accepted == 1
    assert json.loads(post.call_args.kwargs["data"])["events"][0]["name"] == "rented_movie"
