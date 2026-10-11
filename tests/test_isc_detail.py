import unittest
from types import SimpleNamespace

from navigator.ingestion.adapters.isc_detail import amount_from_value, parse_detail_fields, provider_of, quote_prefix
from navigator.ingestion.adapters.isc_index import IscIndexAdapter, merge_repeated_listings

SEPARATE = (
    "Name:\n\nAward A\n\nProvider Name:\n\nSome College\n\nValue:\n\n$1,000\n\nProvince/Territory:\n\nBritish Columbia\n\n"
    "Other Eligibility Criteria:\n\nFirst-year students. Apply early.\n\nContact Information\n\nProvince/Territory:\n\nOntario\n\n"
    "Date modified:\n\n2022-08-22"
)
INLINE = "Name: Award A\n\nProvider Name: Some College\n\nValue: $1,000\n\nProvince/Territory: British Columbia\n\nDate modified: 2022-08-22"


class IscDetailTests(unittest.TestCase):
    def test_labels_are_read_in_both_page_layouts_and_the_first_occurrence_wins(self):
        for text in (SEPARATE, INLINE):
            fields = parse_detail_fields(text)
            self.assertEqual(
                (fields["Name"], fields["Provider Name"], fields["Value"], fields["Province/Territory"]),
                ("Award A", "Some College", "$1,000", "British Columbia"),
            )
            self.assertEqual(fields["Date modified"], "2022-08-22")
        self.assertEqual(
            parse_detail_fields(SEPARATE)["Other Eligibility Criteria"], "First-year students. Apply early."
        )

    def test_a_page_without_a_provider_name_is_read_through_its_contact_organisation(self):
        page = (
            "Name:\n\nMetis Scholar Awards\n\nValue:\n\n$3,500\n\nProvince/Territory:\n\nAlberta\n\nContact Organisation:\n\n"
            "Student Awards and Financial Aid - Lethbridge College\n\nAddress:\n\n3000 College Drive South\n\nDate modified:\n\n2013-11-20"
        )
        self.assertEqual(
            provider_of(parse_detail_fields(page)), ("Student Awards and Financial Aid - Lethbridge College", False)
        )
        self.assertEqual(
            provider_of(parse_detail_fields(SEPARATE)), ("Some College", True)
        )  # a named provider always wins
        self.assertEqual(provider_of({"Name": "X"}), (None, False))  # nothing named: nothing guessed

    def test_an_award_listed_once_per_institution_is_one_opportunity_listed_once(self):
        records = [
            {"id": "b", "source_record_key": "k1", "n": 1},
            {"id": "a", "source_record_key": "k2", "n": 2},
            {"id": "a", "source_record_key": "k1", "n": 3},
            {"id": "a", "source_record_key": "k1", "n": 4},
        ]
        kept, merged = merge_repeated_listings(records)
        # of the repeats of k1 the smallest id wins, then the first listing; the order of the fetches does not matter
        self.assertEqual(([r["n"] for r in kept], merged), ([3, 2], 2))
        self.assertEqual(merge_repeated_listings(list(reversed(records)))[1], 2)
        self.assertEqual(merge_repeated_listings([]), ([], 0))

    def test_amounts_are_only_read_when_the_text_is_unambiguous(self):
        self.assertEqual(amount_from_value("$1,000")["fixed"], "1000")
        self.assertEqual(amount_from_value("$1,000.50")["fixed"], "1000.50")
        self.assertEqual(
            (amount_from_value("Up to $2,500")["kind"], amount_from_value("Up to $2,500")["maximum"]),
            ("maximum", "2500"),
        )
        ranged = amount_from_value("$500 - $1,000")
        self.assertEqual((ranged["kind"], ranged["minimum"], ranged["maximum"]), ("range", "500", "1000"))
        for unclear in ("Varies", "Full tuition", "$500 plus books", "3 x $1,000", None, ""):
            self.assertEqual(amount_from_value(unclear)["kind"], "unspecified", unclear)
            self.assertIsNone(amount_from_value(unclear)["currency"])

    def test_a_quote_is_always_a_verbatim_prefix_within_the_limit(self):
        long_text = "Awarded to a student who shows leadership. " * 20
        quote = quote_prefix(long_text, 300)
        self.assertTrue(long_text.startswith(quote))
        self.assertLessEqual(len(quote), 300)
        self.assertEqual(quote_prefix("Short.", 300), "Short.")

    def test_every_row_of_the_directory_is_followed_and_links_become_https(self):
        rows = (
            "A | British Columbia | X | all | All\nB | Ontario | Y | all | All\nC | National | Z | all | All\n"
            "D | Nunavut | W | all | All\nScholarship/Award | Province"
        )
        doc = SimpleNamespace(
            blocks=[SimpleNamespace(text=rows)],
            links=[
                SimpleNamespace(text=name, href=f"http://www.sac-isc.gc.ca/eng/{i}/{i}")
                for i, name in enumerate(("A", "B", "C", "D", "Not a row"), start=1)
            ],
        )
        source = SimpleNamespace()
        links = IscIndexAdapter().select_links(
            doc, "https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328", source, 0
        )
        # every province and territory, National too; a link that is not a table row is not followed
        self.assertEqual(links, [f"https://www.sac-isc.gc.ca/eng/{i}/{i}" for i in (1, 2, 3, 4)])
        self.assertEqual(IscIndexAdapter().select_links(doc, "x", source, 1), [])


if __name__ == "__main__":
    unittest.main()
