from unittest.mock import patch

import pytest
import requests
import responses

from app import catalog_client, config
from app.catalog_client import CatalogUnavailable
from tests.factories import TWO_SUM

CATALOG = "http://catalog.test"


@pytest.fixture(autouse=True)
def catalog_url():
    with patch.object(config, "CATALOG_URL", CATALOG + "/"):
        yield


@responses.activate
def test_get_problems_sends_ids_and_skips_the_call_when_empty():
    call = responses.get(f"{CATALOG}/problems", json=[TWO_SUM])

    assert catalog_client.get_problems([]) == []
    assert call.call_count == 0

    assert catalog_client.get_problems([1, 5]) == [TWO_SUM]
    assert call.calls[0].request.params == {"ids": "1,5"}


@responses.activate
def test_a_400_from_the_catalog_is_a_value_error():
    responses.post(f"{CATALOG}/problems/pick", status=400, json={"detail": "Unknown topic 'Nope'"})

    with pytest.raises(ValueError, match="Unknown topic 'Nope'"):
        catalog_client.pick_problems(count=1, topics=["Nope"], difficulty="Easy")


@responses.activate
def test_a_502_means_catalog_is_up_but_leetcode_failed_behind_it():
    responses.post(f"{CATALOG}/problems/pick", status=502, body="bad gateway")

    with pytest.raises(RuntimeError, match="Catalog service error 502: bad gateway") as error:
        catalog_client.pick_problems(count=1, topics=["Array"], difficulty="Easy")

    assert not isinstance(error.value, CatalogUnavailable)


@pytest.mark.parametrize("status", [500, 503])
@responses.activate
def test_other_server_errors_mean_the_catalog_is_unavailable(status):
    # 503 is also what Container Apps answers while the catalog is cold-starting.
    responses.post(f"{CATALOG}/problems/pick", status=status, body="App port is not ready")

    with pytest.raises(CatalogUnavailable):
        catalog_client.pick_problems(count=1, topics=["Array"], difficulty="Easy")


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectionError("refused"), requests.Timeout("read timed out")],
)
@responses.activate
def test_an_unreachable_or_slow_catalog_is_unavailable(failure):
    responses.get(f"{CATALOG}/problems", body=failure)

    with pytest.raises(CatalogUnavailable, match="Catalog did not answer"):
        catalog_client.get_problems([1])


def test_every_call_has_a_timeout():
    with patch("app.catalog_client.requests.request") as request:
        request.return_value.status_code = 200
        request.return_value.json.return_value = [TWO_SUM]
        catalog_client.get_problems([1])

    assert request.call_args.kwargs["timeout"] == config.CATALOG_TIMEOUT_S
