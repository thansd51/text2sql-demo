from tests.api.conftest import HarnessFactory, two_datasources

URL = "/api/v1/datasources"


def test_lists_id_name_db_type_and_db_version(make_harness: HarnessFactory) -> None:
    response = make_harness().client.get(URL)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "p001",
            "name": "시험 프로젝트",
            "db_type": "oracle",
            "db_version": "19c",
        }
    ]


def test_every_item_has_exactly_the_four_contract_fields(
    make_harness: HarnessFactory,
) -> None:
    items = make_harness(datasources=two_datasources()).client.get(URL).json()

    assert len(items) == 2
    for item in items:
        assert set(item) == {"id", "name", "db_type", "db_version"}


def test_items_are_ordered_by_id(make_harness: HarnessFactory) -> None:
    items = make_harness(datasources=two_datasources()).client.get(URL).json()

    assert [item["id"] for item in items] == ["a-pg", "p001"]
    assert [(i["db_type"], i["db_version"]) for i in items] == [
        ("postgresql", "14"),
        ("oracle", "19c"),
    ]


def test_empty_registry_returns_an_empty_list(make_harness: HarnessFactory) -> None:
    response = make_harness(datasources={}).client.get(URL)

    assert response.status_code == 200
    assert response.json() == []


def test_internal_details_are_not_exposed(make_harness: HarnessFactory) -> None:
    text = make_harness().client.get(URL).text

    for hidden in (
        "OBJ_MAIN",
        "definition",
        "profiles",
        "metadata_version",
        "v_object",
    ):
        assert hidden not in text


def test_post_is_not_allowed(make_harness: HarnessFactory) -> None:
    assert make_harness().client.post(URL, json={}).status_code == 405
