from src.cv_builder.orcid_resolver import OrcidResolver


class FakeOrcidClient:
    def __init__(self, doi_results=None, title_results=None, records=None):
        self.doi_results = doi_results or {}
        self.title_results = title_results or {}
        self.records = records or {}
        self.doi_calls = []
        self.title_calls = []
        self.record_calls = []

    def search_by_doi(self, doi):
        self.doi_calls.append(doi)
        return self.doi_results.get(doi, [])

    def search_by_title(self, title):
        self.title_calls.append(title)
        return self.title_results.get(title, [])

    def get_record(self, orcid):
        self.record_calls.append(orcid)
        return self.records.get(orcid, {})


def make_record(orcid="0000-0001-0000-0000", credit_name="", given_names="", family_name=""):
    return {
        "orcid-identifier": {"path": orcid},
        "person": {
            "name": {
                "credit-name": {"value": credit_name},
                "given-names": {"value": given_names},
                "family-name": {"value": family_name},
            }
        },
    }


def test_orcid_resolver_rejects_name_only_match_without_work_evidence():
    record = make_record(credit_name="Ada Lovelace")
    client = FakeOrcidClient(records={"0000-0001-0000-0000": record})

    assert OrcidResolver(client).resolve({"display_name": "Ada Lovelace"}, []) == ("", {})
    assert client.record_calls == []


def test_orcid_resolver_accepts_two_exact_doi_matches():
    record = make_record(credit_name="Different Person")
    client = FakeOrcidClient(
        doi_results={
            "10.1234/one": ["0000-0001-0000-0000"],
            "10.1234/two": ["0000-0001-0000-0000"],
        },
        records={"0000-0001-0000-0000": record},
    )
    works = [
        {"doi": "10.1234/one", "display_name": "First Paper"},
        {"doi": "10.1234/two", "display_name": "Second Paper"},
    ]

    assert OrcidResolver(client).resolve({"display_name": "Ada Lovelace"}, works) == (
        "0000-0001-0000-0000",
        record,
    )


def test_orcid_resolver_accepts_single_doi_match_when_record_name_matches_alias():
    record = make_record(credit_name="A. Lovelace")
    client = FakeOrcidClient(
        doi_results={"10.1234/one": ["0000-0001-0000-0000"]},
        records={"0000-0001-0000-0000": record},
    )
    works = [
        {
            "doi": "10.1234/one",
            "display_name": "Reliable Paper",
            "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        }
    ]

    assert OrcidResolver(client).resolve({"display_name": "Augusta Ada King"}, works) == (
        "0000-0001-0000-0000",
        record,
    )


def test_orcid_resolver_rejects_single_doi_match_when_record_name_does_not_match():
    record = make_record(credit_name="Grace Hopper")
    client = FakeOrcidClient(
        doi_results={"10.1234/one": ["0000-0001-0000-0000"]},
        records={"0000-0001-0000-0000": record},
    )
    works = [{"doi": "10.1234/one", "display_name": "Reliable Paper"}]

    assert OrcidResolver(client).resolve({"display_name": "Ada Lovelace"}, works) == ("", {})


def test_orcid_resolver_accepts_two_title_matches_with_name_match():
    record = make_record(given_names="Ada", family_name="Lovelace")
    client = FakeOrcidClient(
        title_results={
            "First Reliable Paper": ["0000-0001-0000-0000"],
            "Second Reliable Paper": ["0000-0001-0000-0000"],
        },
        records={"0000-0001-0000-0000": record},
    )
    works = [
        {"display_name": "First Reliable Paper"},
        {"title": "Second Reliable Paper"},
    ]

    assert OrcidResolver(client).resolve({"display_name": "Ada Lovelace"}, works) == (
        "0000-0001-0000-0000",
        record,
    )
