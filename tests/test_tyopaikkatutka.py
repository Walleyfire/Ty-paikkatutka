import inspect
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tyopaikkatutka
import job_agent


def test_config():
    return {
        "app": {
            "minimum_score": 38,
            "request_timeout_seconds": 2,
            "maximum_details_per_source": 10,
            "days_to_show": 60,
        },
        "profile": {
            "name": "Miika Väyrynen",
            "email": "miika@example.com",
            "phone": "040 000 0000",
            "portfolio": "https://example.com",
            "preferred_locations": ["Vantaa", "Helsinki", "Espoo"],
            "acceptable_locations": ["Uusimaa"],
            "roles": [
                "varastotyöntekijä",
                "pakkaaja",
                "siivooja",
                "tuotantotyöntekijä",
            ],
            "strengths": ["varastonhoitajan koulutus"],
            "qualifications": {
                "B-ajokortti": "unknown",
                "trukkikortti": "no",
                "työturvallisuuskortti": "unknown",
                "hygieniapassi": "unknown",
            },
            "excluded_phrases": ["pelkkä provisiopalkka"],
        },
        "sources": [],
    }


class FakeHtmlClient:
    def get_text(self, url):
        if url.endswith("/jobs"):
            return (
                """
                <html><body>
                  <a href="/jobs/varastotyontekija-vantaa">
                    Varastotyöntekijä Vantaalle
                  </a>
                </body></html>
                """,
                url,
            )
        return (
            """
            <html><head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "JobPosting",
              "title": "Varastotyöntekijä",
              "description": "<p>Keräilyä ja pakkaamista.</p>",
              "hiringOrganization": {"name": "Testiyritys Oy"},
              "jobLocation": {
                "@type": "Place",
                "address": {"addressLocality": "Vantaa", "addressCountry": "FI"}
              },
              "validThrough": "2026-08-15",
              "url": "https://example.com/jobs/varastotyontekija-vantaa"
            }
            </script></head><body><h1>Varastotyöntekijä</h1></body></html>
            """,
            url,
        )


class FakeWorkdayClient:
    def __init__(self):
        self.post_payloads = []

    def post_json(self, url, payload):
        self.post_payloads.append(payload)
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Pakkaaja",
                    "externalPath": "/job/Vantaa/Pakkaaja_R1",
                    "locationsText": "Vantaa",
                    "postedOn": "Tänään",
                }
            ],
        }

    def get_json(self, url):
        return {
            "jobPostingInfo": {
                "title": "Pakkaaja",
                "company": "Posti",
                "location": "Vantaa",
                "jobDescription": "<p>Pakkaus- ja varastotyötä.</p>",
                "endDate": "2026-08-01",
            }
        }


class FakeWordPressClient:
    def get_json(self, url):
        return [
            {
                "id": 1,
                "date": "2026-07-27T08:00:00",
                "link": "https://www.workpower.fi/tyopaikat/varastotyontekija-vantaa-1/",
                "title": {"rendered": "Varastotyöntekijä, Vantaa"},
                "content": {
                    "rendered": "<p>Keräilyä ja pakkaamista Vantaan varastossa.</p>"
                },
                "meta": {
                    "rendered_listing": (
                        "<span>Vantaa</span><span>Haku päättyy "
                        "<b>15.8.2026</b></span>"
                    )
                },
            }
        ]


class FakeEezyClient:
    def __init__(self):
        self.post_payloads = []

    def post_json(self, url, payload):
        self.post_payloads.append((url, payload))
        return {
            "data": {
                "elasticJobs": {
                    "pageResults": {
                        "available": 2,
                        "from": 0,
                        "to": 2,
                    },
                    "jobs": [
                        {
                            "id": "job-101",
                            "name": "Varastotyöntekijä, Vantaa",
                            "customer": "Varasto Oy",
                            "customerDescription": "",
                            "hideCustomer": False,
                            "descriptionPlain": (
                                "<p>Keräilyä ja pakkaamista Vantaan varastossa.</p>"
                            ),
                            "endTime": "2099-08-15T20:59:59Z",
                            "startTime": "2099-07-30T06:18:33Z",
                            "fieldOfWorks": ["Logistiikkapalvelut"],
                            "workLocations": [
                                {"name": "Vantaa"},
                                {"name": "Uusimaa"},
                                {"name": "Vantaa"},
                            ],
                        },
                        {
                            "id": "open-application",
                            "name": "Avoin hakemus varastotyöhön",
                            "customer": "Eezy Oyj",
                            "hideCustomer": True,
                            "descriptionPlain": "",
                            "endTime": "",
                            "startTime": "",
                            "fieldOfWorks": [],
                            "workLocations": [],
                        },
                    ],
                }
            }
        }


class FakeSitemapClient:
    def get_text(self, url):
        if url.endswith("/jobs"):
            return "<html><body><h1>Työpaikat</h1></body></html>", url
        if url.endswith("/sitemap.xml"):
            return (
                """
                <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <sitemap><loc>https://example.com/jobs-sitemap.xml</loc></sitemap>
                </sitemapindex>
                """,
                url,
            )
        if url.endswith("/jobs-sitemap.xml"):
            return (
                """
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url>
                    <loc>https://example.com/jobs/varastotyontekija-vantaa-101</loc>
                    <lastmod>2099-01-02</lastmod>
                  </url>
                  <url>
                    <loc>https://example.com/jobs/siivooja-helsinki-100</loc>
                    <lastmod>2000-01-02</lastmod>
                  </url>
                  <url><loc>https://example.com/uutiset/muu-sivu</loc></url>
                </urlset>
                """,
                url,
            )
        if url.endswith("-101"):
            return (
                """
                <html><head><meta name="description" content="Keräilyä ja pakkaamista.">
                </head><body><h1>Varastotyöntekijä</h1>
                <p>Työpaikka sijaitsee Vantaalla. Hakuaika päättyy 31.12.2099.</p>
                </body></html>
                """,
                url,
            )
        return (
            """
            <html><body><h1>Siivooja</h1>
            <p>Työpaikka sijaitsee Helsingissä. Hakuaika päättyy 1.1.2000.</p>
            </body></html>
            """,
            url,
        )


class FakeFeedClient:
    def get_text(self, url):
        if "format=rss" in url:
            return (
                """
                <rss version="2.0">
                  <channel>
                    <item>
                      <title>Varastotyöntekijä, Vantaa</title>
                      <link>https://example.com/jobs/varastotyontekija-101</link>
                      <description>
                        Keräilyä ja pakkaamista Vantaalla.
                        Haku päättyy 31.12.2099.
                      </description>
                      <pubDate>30.7.2099</pubDate>
                    </item>
                    <item>
                      <title>Avoin hakemus</title>
                      <link>https://example.com/jobs/avoin-hakemus-100</link>
                    </item>
                  </channel>
                </rss>
                """,
                url,
            )
        return (
            """
            <html><head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "JobPosting",
              "title": "Varastotyöntekijä",
              "description": "<p>Keräilyä ja pakkaamista.</p>",
              "hiringOrganization": {"name": "Kunnan Varasto Oy"},
              "jobLocation": {
                "@type": "Place",
                "address": {"addressLocality": "Vantaa", "addressCountry": "FI"}
              },
              "validThrough": "2099-12-31",
              "url": "https://example.com/jobs/varastotyontekija-101"
            }
            </script></head><body><h1>Varastotyöntekijä</h1></body></html>
            """,
            url,
        )


class TyopaikkatutkaTests(unittest.TestCase):
    def test_proprietary_license_and_statistics_finland_notice_are_present(self):
        root = Path(__file__).resolve().parents[1]
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        notice_text = (root / "NOTICE.md").read_text(encoding="utf-8")
        readme_text = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("Copyright © 2026 Miika Väyrynen", license_text)
        self.assertIn("Kaikki oikeudet pidätetään", license_text)
        self.assertIn("jatkokehittäminen", license_text)
        self.assertIn("Tilastokeskus, CC BY 4.0", notice_text)
        self.assertIn("Kunnat 2026", notice_text)
        self.assertIn("TK10-ammattiluokitus", notice_text)
        self.assertIn(
            "Versio **1.6.1** on Työpaikkatutkan ensimmäinen julkisesti "
            "saatavilla oleva",
            readme_text,
        )
        self.assertNotIn("## Päivitys versiosta", readme_text)
        self.assertIn(
            "Baronan omat työpaikkasivut on jätetty kokonaan pois",
            readme_text,
        )
        self.assertIn("HTTP 403", readme_text)
        self.assertIn("ei yritä kiertää sivuston", readme_text)
        for release_feature in (
            "24 valittavasta suomalaisesta",
            "kaikki Suomen 308 kuntaa ja 19 maakuntaa",
            "481 Suomessa käytössä olevaa",
            "yli 120 vaihtoehtoa",
            "SQLite-tietokanta säilyttää hakuhistorian",
            "Työpaikkatutka ei lähetä hakemuksia tai sähköpostia automaattisesti",
        ):
            self.assertIn(release_feature, readme_text)

    def test_branding_and_icon_assets(self):
        self.assertEqual("Työpaikkatutka", tyopaikkatutka.APP_NAME)
        self.assertEqual("1.6.1", tyopaikkatutka.APP_VERSION)
        self.assertEqual(8, tyopaikkatutka.PROFILE_SELECTION_LIST_HEIGHT)
        self.assertEqual(
            b"\x89PNG\r\n\x1a\n",
            tyopaikkatutka.APP_ICON_PNG_PATH.read_bytes()[:8],
        )
        self.assertEqual(
            b"\x00\x00\x01\x00",
            tyopaikkatutka.APP_ICON_ICO_PATH.read_bytes()[:4],
        )
        icon_bytes = tyopaikkatutka.APP_ICON_ICO_PATH.read_bytes()
        first_frame_offset = int.from_bytes(icon_bytes[18:22], "little")
        self.assertEqual(
            b"\x28\x00\x00\x00",
            icon_bytes[first_frame_offset : first_frame_offset + 4],
        )

    def test_old_launcher_and_shortcut_creator_target_tyopaikkatutka(self):
        self.assertIs(job_agent.main, tyopaikkatutka.main)
        root = Path(__file__).resolve().parents[1]
        shortcut_script = (root / "LUO_PIKAKUVAKE.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('"tyopaikkatutka.py"', shortcut_script)
        self.assertIn("pythonw.exe", shortcut_script)
        self.assertIn("IconLocation", shortcut_script)

    def test_windows_theme_detection_reads_app_mode(self):
        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        fake_winreg = mock.Mock()
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.OpenKey.return_value = FakeKey()

        with (
            mock.patch.object(tyopaikkatutka.sys, "platform", "win32"),
            mock.patch.dict(sys.modules, {"winreg": fake_winreg}),
        ):
            fake_winreg.QueryValueEx.return_value = (0, None)
            self.assertTrue(tyopaikkatutka.windows_prefers_dark())
            fake_winreg.QueryValueEx.return_value = (1, None)
            self.assertFalse(tyopaikkatutka.windows_prefers_dark())

        fake_winreg.OpenKey.assert_called_with(
            fake_winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )

    def test_windows_theme_detection_falls_back_to_light(self):
        with mock.patch.object(tyopaikkatutka.sys, "platform", "linux"):
            self.assertFalse(tyopaikkatutka.windows_prefers_dark())

        fake_winreg = mock.Mock()
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.OpenKey.side_effect = OSError("Asetusta ei löytynyt")
        with (
            mock.patch.object(tyopaikkatutka.sys, "platform", "win32"),
            mock.patch.dict(sys.modules, {"winreg": fake_winreg}),
        ):
            self.assertFalse(tyopaikkatutka.windows_prefers_dark())

    def test_theme_palettes_cover_all_job_status_colours(self):
        light = tyopaikkatutka.theme_palette(False)
        dark = tyopaikkatutka.theme_palette(True)
        self.assertNotEqual(light["background"], dark["background"])
        self.assertNotEqual(light["foreground"], dark["foreground"])
        self.assertEqual("#06101d", dark["background"])
        self.assertEqual("#0a1a2c", dark["card"])
        self.assertEqual("#20d3f3", dark["accent"])
        for tag in ("good", "medium", "republished", "applied", "ignored", "expired"):
            for suffix in ("background", "foreground"):
                key = f"{tag}_{suffix}"
                self.assertTrue(light[key])
                self.assertTrue(dark[key])

    def test_windows_colorref_converts_rgb_order(self):
        self.assertEqual(0x1D1006, tyopaikkatutka.windows_colorref("#06101d"))
        self.assertEqual(0xF3D320, tyopaikkatutka.windows_colorref("#20d3f3"))
        with self.assertRaises(ValueError):
            tyopaikkatutka.windows_colorref("#fff")

    def test_selected_settings_tab_is_larger_than_unselected_tab(self):
        selected_height, selected_font, selected_padding = (
            tyopaikkatutka.settings_tab_dimensions(True)
        )
        normal_height, normal_font, normal_padding = (
            tyopaikkatutka.settings_tab_dimensions(False)
        )
        self.assertGreater(selected_height, normal_height)
        self.assertGreater(selected_font, normal_font)
        self.assertGreater(selected_padding, normal_padding)

    def test_rounded_control_points_stay_inside_bounds(self):
        points = tyopaikkatutka.rounded_polygon_points(1, 2, 101, 42, 8)
        x_coordinates = points[0::2]
        y_coordinates = points[1::2]
        self.assertEqual(1, min(x_coordinates))
        self.assertEqual(101, max(x_coordinates))
        self.assertEqual(2, min(y_coordinates))
        self.assertEqual(42, max(y_coordinates))

    def test_windows_titlebar_uses_theme_colours(self):
        import ctypes

        root = mock.Mock()
        root.winfo_id.return_value = 123
        fake_windll = mock.Mock()
        fake_windll.user32.GetParent.return_value = 456
        fake_windll.dwmapi.DwmSetWindowAttribute.return_value = 0
        palette = tyopaikkatutka.theme_palette(True)

        with (
            mock.patch.object(tyopaikkatutka.sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", fake_windll, create=True),
        ):
            self.assertTrue(
                tyopaikkatutka.apply_windows_titlebar_theme(root, True, palette)
            )

        attributes = [
            item.args[1]
            for item in fake_windll.dwmapi.DwmSetWindowAttribute.call_args_list
        ]
        self.assertEqual([20, 34, 35, 36], attributes)
        root.update_idletasks.assert_called_once_with()
        fake_windll.user32.GetParent.assert_called_once_with(123)

    def test_windows_native_titlebar_icon_sets_small_and_big_icons(self):
        import ctypes

        root = mock.Mock()
        root.winfo_id.return_value = 123
        fake_windll = mock.Mock()
        fake_windll.user32.GetParent.return_value = 456
        fake_windll.user32.LoadImageW.side_effect = [111, 222]

        with (
            mock.patch.object(tyopaikkatutka.sys, "platform", "win32"),
            mock.patch.object(ctypes, "windll", fake_windll, create=True),
        ):
            handles = tyopaikkatutka.apply_windows_window_icon(root)

        self.assertEqual((111, 222), handles)
        self.assertEqual(2, fake_windll.user32.LoadImageW.call_count)
        self.assertEqual(
            [
                mock.call(456, 0x0080, 0, 111),
                mock.call(456, 0x0080, 1, 222),
            ],
            fake_windll.user32.SendMessageW.call_args_list,
        )

    def test_deadline_sort_toggles_dates_and_keeps_missing_last(self):
        rows = [
            {"title": "Ei määräpäivää", "deadline": ""},
            {"title": "Myöhempi", "deadline": "31.12.2030"},
            {"title": "Aikaisempi", "deadline": "2026-08-15"},
            {"title": "Keskimmäinen", "deadline": "1.9.2027"},
        ]
        earliest = tyopaikkatutka.sort_jobs_by_deadline(rows, latest_first=False)
        latest = tyopaikkatutka.sort_jobs_by_deadline(rows, latest_first=True)
        self.assertEqual(
            ["Aikaisempi", "Keskimmäinen", "Myöhempi", "Ei määräpäivää"],
            [row["title"] for row in earliest],
        )
        self.assertEqual(
            ["Myöhempi", "Keskimmäinen", "Aikaisempi", "Ei määräpäivää"],
            [row["title"] for row in latest],
        )

    def test_score_sort_toggles_highest_and_lowest_first(self):
        rows = [
            {"title": "Keskimmäinen", "score": 55},
            {"title": "Paras", "score": 91},
            {"title": "Matalin", "score": 24},
        ]
        highest = tyopaikkatutka.sort_jobs_by_score(rows, highest_first=True)
        lowest = tyopaikkatutka.sort_jobs_by_score(rows, highest_first=False)
        self.assertEqual(
            ["Paras", "Keskimmäinen", "Matalin"],
            [row["title"] for row in highest],
        )
        self.assertEqual(
            ["Matalin", "Keskimmäinen", "Paras"],
            [row["title"] for row in lowest],
        )

    def test_deadline_display_uses_only_finnish_date(self):
        self.assertEqual(
            "15.08.2026",
            tyopaikkatutka.format_job_date("2026-08-15T21:59:00.000Z"),
        )
        self.assertEqual(
            "01.09.2027",
            tyopaikkatutka.format_job_date("1.9.2027 klo 23.59"),
        )
        self.assertEqual("", tyopaikkatutka.format_job_date(""))
        self.assertEqual("", tyopaikkatutka.format_job_date("ei määräpäivää"))

    def test_finland_location_data_covers_all_2026_municipalities(self):
        self.assertEqual(19, len(tyopaikkatutka.FINLAND_REGIONS))
        self.assertEqual(308, len(tyopaikkatutka.FINLAND_MUNICIPALITIES))
        self.assertEqual(26, len(tyopaikkatutka.FINLAND_REGIONS["Uusimaa"]))
        self.assertIn("Vantaa", tyopaikkatutka.FINLAND_REGIONS["Uusimaa"])
        self.assertIn("Rovaniemi", tyopaikkatutka.FINLAND_REGIONS["Lappi"])

    def test_region_choice_matches_its_municipalities(self):
        self.assertEqual(
            ["Uusimaa"],
            tyopaikkatutka.matching_location_choices(
                "Varastotyöntekijä Vantaalla",
                ["Uusimaa"],
            ),
        )
        self.assertEqual(
            ["Uusimaa"],
            tyopaikkatutka.matching_location_choices(
                "Siivooja Porvoossa",
                ["Uusimaa"],
            ),
        )
        self.assertEqual(
            [],
            tyopaikkatutka.matching_location_choices(
                "Tuotantotyöntekijä Turussa",
                ["Uusimaa"],
            ),
        )

    def test_location_choice_supports_city_custom_text_and_whole_finland(self):
        self.assertEqual(
            "Uusimaa",
            tyopaikkatutka.normalize_location_choice("Uusimaa — maakunta"),
        )
        self.assertEqual(
            "Vantaa",
            tyopaikkatutka.normalize_location_choice("Vantaa — kunta"),
        )
        self.assertEqual(
            ["Koko Suomi"],
            tyopaikkatutka.matching_location_choices(
                "Työpaikka missä tahansa",
                ["Koko Suomi"],
            ),
        )
        self.assertEqual(
            ["pääkaupunkiseutu"],
            tyopaikkatutka.matching_location_choices(
                "Työpaikka pääkaupunkiseudulla",
                ["pääkaupunkiseutu"],
            ),
        )

    def test_choice_search_shows_matching_locations_and_keeps_custom_values(self):
        matches = tyopaikkatutka.selectable_choice_matches(
            "vant",
            tyopaikkatutka.LOCATION_CHOICES,
        )
        self.assertEqual("Vantaa — kunta", matches[0])
        self.assertNotIn("Turku — kunta", matches)
        self.assertEqual(
            "Oma lähialue",
            tyopaikkatutka.normalize_location_choice("Oma lähialue"),
        )

    def test_strength_catalogue_is_broad_searchable_and_has_no_duplicates(self):
        strengths = tyopaikkatutka.STRENGTH_CHOICES
        self.assertGreaterEqual(len(strengths), 120)
        self.assertEqual(
            len(strengths),
            len({tyopaikkatutka.fold_text(item) for item in strengths}),
        )
        for expected in (
            "huolellinen",
            "hyvät tietokonetaidot",
            "oma-aloitteinen",
            "varastonhoitajan koulutus",
            "valmis fyysiseen työhön",
        ):
            self.assertIn(expected, strengths)
        matches = tyopaikkatutka.selectable_choice_matches(
            "järjest",
            strengths,
        )
        self.assertIn("järjestelmällinen", matches)
        self.assertIn("järjestyksen ylläpitäminen", matches)

    def test_finland_occupation_catalogue_contains_all_tk10_classes(self):
        occupations = tyopaikkatutka.FINLAND_OCCUPATIONS
        self.assertEqual(481, len(occupations))
        self.assertEqual(481, len({code for code, _ in occupations}))
        self.assertEqual(481, len(tyopaikkatutka.OCCUPATION_CHOICES))
        self.assertIn("Varastonhoitajat ym.", tyopaikkatutka.OCCUPATION_CHOICES)
        self.assertIn(
            "Rahdinkäsittelijät, varastotyöntekijät ym.",
            tyopaikkatutka.OCCUPATION_CHOICES,
        )

    def test_occupation_search_supports_official_and_custom_job_titles(self):
        matches = tyopaikkatutka.selectable_choice_matches(
            "varasto",
            tyopaikkatutka.OCCUPATION_CHOICES,
        )
        self.assertIn("Varastonhoitajat ym.", matches)
        self.assertIn(
            "Rahdinkäsittelijät, varastotyöntekijät ym.",
            matches,
        )
        self.assertEqual(
            "oma erikoistehtävä",
            tyopaikkatutka.normalize_occupation_choice("oma erikoistehtävä"),
        )

    def test_official_plural_occupation_matches_singular_job_title(self):
        self.assertTrue(
            tyopaikkatutka.role_matches_text(
                "Varastonhoitajat ym.",
                "Varastonhoitaja Vantaalle",
            )
        )
        self.assertTrue(
            tyopaikkatutka.role_matches_text(
                "Rahdinkäsittelijät, varastotyöntekijät ym.",
                "Haemme varastotyöntekijää terminaaliin",
            )
        )
        self.assertTrue(
            tyopaikkatutka.role_matches_text(
                "Kokit, keittäjät ja kylmäköt",
                "Kokki lounasravintolaan",
            )
        )
        self.assertFalse(
            tyopaikkatutka.role_matches_text(
                "Varastonhoitajat ym.",
                "Kirjanpitäjä",
            )
        )

    def test_excluded_phrase_selector_has_only_existing_default_choices(self):
        expected = (
            "pelkkä provisiopalkka",
            "ainoastaan provisio",
            "toimeksiantosopimus",
            "kevyt-yrittäjä",
            "kevytyrittäjä",
            "franchising-yrittäjä",
            "maksullinen koulutus",
        )
        self.assertEqual(expected, tyopaikkatutka.EXCLUDED_PHRASE_CHOICES)
        self.assertEqual(
            ["pelkkä provisiopalkka", "ainoastaan provisio"],
            tyopaikkatutka.selectable_choice_matches(
                "provisio",
                tyopaikkatutka.EXCLUDED_PHRASE_CHOICES,
            ),
        )
        self.assertEqual(
            "oma poissulkeva ehto",
            tyopaikkatutka.normalize_excluded_phrase(
                "  oma   poissulkeva ehto  "
            ),
        )

    def test_choice_search_keeps_typing_focus_instead_of_posting_popup(self):
        source = inspect.getsource(
            tyopaikkatutka.TyopaikkatutkaGUI._settings_choice_box
        )
        self.assertNotIn("ttk::combobox::Post", source)
        self.assertIn("suggestion_list", source)
        self.assertIn("selector.focus_set()", source)

    def test_nested_choice_list_scroll_does_not_reach_settings_page(self):
        class FakeWidget:
            def __init__(self):
                self.bindings = {}
                self.scrolls = []

            def bind(self, event_name, callback):
                self.bindings[event_name] = callback

            def yview_scroll(self, units, mode):
                self.scrolls.append((units, mode))

        listbox = FakeWidget()
        scrollbar = FakeWidget()
        gui = object.__new__(tyopaikkatutka.TyopaikkatutkaGUI)
        gui._bind_nested_vertical_scroll(listbox, scrollbar)

        result = listbox.bindings["<MouseWheel>"](
            mock.Mock(delta=-120, num=None)
        )
        self.assertEqual("break", result)
        self.assertEqual([(1, "units")], listbox.scrolls)
        self.assertIn("<MouseWheel>", scrollbar.bindings)
        self.assertIn("<Button-4>", scrollbar.bindings)
        self.assertIn("<Button-5>", scrollbar.bindings)

    def test_nationwide_location_detection_handles_inflections_without_ii_false_match(self):
        self.assertEqual(
            ["Rovaniemi"],
            tyopaikkatutka.detect_finland_locations(
                "Työpaikka sijaitsee Rovaniemellä"
            ),
        )
        self.assertEqual(
            ["Helsinki"],
            tyopaikkatutka.detect_finland_locations("Siivooja Helsingissä"),
        )
        self.assertNotIn(
            "Ii",
            tyopaikkatutka.detect_finland_locations("Kokenut siivooja"),
        )

    def test_selected_region_filters_out_other_recognized_regions(self):
        config = test_config()
        config["profile"]["preferred_locations"] = []
        config["profile"]["acceptable_locations"] = ["Uusimaa"]
        self.assertTrue(
            tyopaikkatutka.job_matches_location_filter(
                tyopaikkatutka.Job(
                    title="Varastotyöntekijä",
                    company="Testi Oy",
                    location="Vantaa",
                    url="https://example.com/vantaa",
                    source="Testi",
                ),
                config,
            )
        )
        self.assertFalse(
            tyopaikkatutka.job_matches_location_filter(
                tyopaikkatutka.Job(
                    title="Varastotyöntekijä",
                    company="Testi Oy",
                    location="Turku",
                    url="https://example.com/turku",
                    source="Testi",
                ),
                config,
            )
        )
        self.assertTrue(
            tyopaikkatutka.job_matches_location_filter(
                tyopaikkatutka.Job(
                    title="Varastotyöntekijä",
                    company="Testi Oy",
                    location="",
                    url="https://example.com/tarkista",
                    source="Testi",
                ),
                config,
            )
        )

    def test_custom_capital_region_and_whole_finland_filters(self):
        config = test_config()
        config["profile"]["preferred_locations"] = ["pääkaupunkiseutu"]
        config["profile"]["acceptable_locations"] = []
        helsinki = tyopaikkatutka.Job(
            title="Siivooja",
            company="Testi Oy",
            location="Helsinki",
            url="https://example.com/helsinki",
            source="Testi",
        )
        self.assertTrue(tyopaikkatutka.job_matches_location_filter(helsinki, config))
        config["profile"]["preferred_locations"] = ["Koko Suomi"]
        helsinki.location = "Rovaniemi"
        self.assertTrue(tyopaikkatutka.job_matches_location_filter(helsinki, config))

    def test_visual_settings_update_preserves_technical_source_data(self):
        config = test_config()
        config["app"]["duplicate_window_days"] = 60
        config["profile"]["qualifications"] = {
            "B-ajokortti": "no",
            "trukkikortti": "unknown",
        }
        config["sources"] = [
            {
                "name": "Testilähde",
                "type": "html",
                "url": "https://example.com/jobs",
                "link_patterns": ["example\\.com/jobs/.+"],
                "enabled": True,
            }
        ]
        values = {
            "profile.name": "Miika Väyrynen",
            "profile.email": "miika@example.com",
            "profile.phone": "040 000 0000",
            "profile.portfolio": "https://miikavayrynen.web.app",
            "profile.home_city": "Vantaa",
            "profile.preferred_locations": "Vantaa\nHelsinki\nvantaa",
            "profile.acceptable_locations": "Uusimaa\nEspoo",
            "profile.roles": "varastotyöntekijä\nsiivooja",
            "profile.strengths": "huolellinen\noma-aloitteinen",
            "profile.excluded_phrases": "pelkkä provisiopalkka",
            "profile.qualifications": {
                "B-ajokortti": "no",
                "trukkikortti": "yes",
            },
            "app.minimum_score": "45",
            "app.days_to_show": "90",
            "app.duplicate_window_days": "75",
            "app.request_timeout_seconds": "30",
            "app.maximum_details_per_source": "100",
        }
        updated = tyopaikkatutka.update_config_from_settings(config, values, [False])
        self.assertEqual(["Vantaa", "Helsinki"], updated["profile"]["preferred_locations"])
        self.assertEqual("yes", updated["profile"]["qualifications"]["trukkikortti"])
        self.assertEqual(45, updated["app"]["minimum_score"])
        self.assertFalse(updated["sources"][0]["enabled"])
        self.assertEqual(
            ["example\\.com/jobs/.+"],
            updated["sources"][0]["link_patterns"],
        )
        self.assertNotIn("email", updated)
        self.assertTrue(config["sources"][0]["enabled"])

    def test_visual_settings_validation_rejects_invalid_values(self):
        config = test_config()
        config["app"]["duplicate_window_days"] = 60
        values = {
            "profile.name": "Miika",
            "profile.roles": "",
            "app.minimum_score": "101",
            "app.days_to_show": "60",
            "app.duplicate_window_days": "60",
            "app.request_timeout_seconds": "25",
            "app.maximum_details_per_source": "80",
        }
        with self.assertRaisesRegex(ValueError, "työtehtäviä"):
            tyopaikkatutka.update_config_from_settings(config, values, [])
        values["profile.roles"] = "varastotyöntekijä"
        with self.assertRaisesRegex(ValueError, "0–100"):
            tyopaikkatutka.update_config_from_settings(config, values, [])

    def test_visual_settings_write_config_creates_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "config.json"
            path.write_text('{"old": true}\n', encoding="utf-8")
            updated = {"app": {"minimum_score": 42}, "sources": []}
            with mock.patch.object(tyopaikkatutka, "BACKUP_DIR", root / "varmuuskopiot"):
                tyopaikkatutka.write_config_file(updated, path)
            self.assertEqual(
                updated,
                json.loads(path.read_text(encoding="utf-8")),
            )
            backups = list((root / "varmuuskopiot").glob("config_ennen_*.json"))
            self.assertEqual(1, len(backups))
            self.assertEqual(
                {"old": True},
                json.loads(backups[0].read_text(encoding="utf-8")),
            )

    def test_config_migration_removes_contact_and_barona_sources(self):
        old = test_config()
        old["profile"]["email"] = "oma@example.com"
        old["app"]["email_on_first_run"] = True
        old["email"] = {
            "enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
        }
        old["sources"] = [
            {
                "name": "Barona – Vantaa",
                "type": "html",
                "url": "https://www.baronacareers.com/fi/fi/job/vantaa-01-fi-2",
                "enabled": False,
            }
        ]
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        migrated, changed = tyopaikkatutka.merge_config_defaults(old, defaults)
        self.assertTrue(changed)
        for key in ("name", "email", "phone", "portfolio", "home_city"):
            self.assertNotIn(key, migrated["profile"])
        self.assertEqual("no", migrated["profile"]["qualifications"]["B-ajokortti"])
        self.assertEqual(8, migrated["app"]["config_version"])
        self.assertNotIn("email", migrated)
        self.assertNotIn("email_on_first_run", migrated["app"])
        names = {source["name"] for source in migrated["sources"]}
        self.assertFalse(any("barona" in name.lower() for name in names))
        self.assertTrue(
            {
                "StaffPoint",
                "WorkPower",
                "Duunitori",
                "Jobly",
                "Laura.fi – Uusimaa",
                "Kuntarekry",
                "Helsinki Rekry",
                "Valtiolle.fi",
                "Bolt.Works",
                "Seure",
                "Kesko",
                "Palmia",
                "Vantti",
                "Eezy",
                "Manpower",
                "Bondata",
                "Amiko",
                "Worker",
                "RTK-Henkilöstöpalvelu",
            }
            <= names
        )

    def test_default_config_has_expanded_qualifications_without_contact_or_barona(self):
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(8, defaults["app"]["config_version"])
        self.assertEqual(20, len(defaults["profile"]["qualifications"]))
        self.assertEqual(
            {
                key
                for _, entries in tyopaikkatutka.QUALIFICATION_GROUPS
                for key, _ in entries
            },
            set(defaults["profile"]["qualifications"]),
        )
        for key in ("name", "email", "phone", "portfolio", "home_city"):
            self.assertNotIn(key, defaults["profile"])
        self.assertFalse(
            any(
                "barona" in source.get("name", "").lower()
                or "baronacareers.com" in source.get("url", "").lower()
                for source in defaults["sources"]
            )
        )

    def test_source_catalog_is_grouped_and_new_sources_require_selection(self):
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        by_name = {source["name"]: source for source in defaults["sources"]}
        new_sources = {
            "Eezy",
            "Manpower",
            "Bondata",
            "Amiko",
            "Worker",
            "RTK-Henkilöstöpalvelu",
        }
        self.assertEqual(24, len(by_name))
        self.assertTrue(new_sources <= set(by_name))
        self.assertTrue(
            all(not by_name[name]["enabled"] for name in new_sources)
        )
        self.assertEqual("eezy", by_name["Eezy"]["type"])
        self.assertEqual(
            "https://api.eezy.fi/api",
            by_name["Eezy"]["api_url"],
        )
        sample_urls = {
            "Eezy": "https://tyopaikat.eezy.fi/tyopaikat/yj9OQ",
            "Manpower": (
                "https://www.manpower.fi/tyo/"
                "pelimyyjat-lauantaivuoroihin-powerparkkiin-hb-leisure-280545"
            ),
            "Bondata": (
                "https://henkilostopalvelut.bondata.fi/tyonhakijalle/"
                "avoimet-tyopaikat/logistiikkatyontekija-mxweqg/"
            ),
            "Amiko": (
                "https://www.amiko.fi/tyopaikat/"
                "dsv-nurmijarvi-hakee-terminaalityontekijoita/"
            ),
            "Worker": (
                "https://www.worker.fi/job/"
                "rakennusapulainen-helsinkiin-talonrakennus-ja-lvis-ala/"
            ),
            "RTK-Henkilöstöpalvelu": (
                "https://rtkhenkilostopalvelu.fi/avoimet-tyopaikat/?id=49849545"
            ),
        }
        for name, url in sample_urls.items():
            self.assertTrue(
                any(
                    re.search(pattern, url)
                    for pattern in by_name[name]["link_patterns"]
                ),
                name,
            )
        self.assertIn(
            "Varasto ja logistiikka",
            tyopaikkatutka.source_job_categories(by_name["Posti"]),
        )
        self.assertIn(
            "Siivous ja kiinteistöpalvelut",
            tyopaikkatutka.source_job_categories(by_name["SOL"]),
        )
        self.assertEqual(
            (tyopaikkatutka.SOURCE_FILTER_OTHER,),
            tyopaikkatutka.source_job_categories(
                {
                    "name": "Oma lähde",
                    "url": "https://example.com/jobs",
                }
            ),
        )
        source_ui = inspect.getsource(
            tyopaikkatutka.TyopaikkatutkaGUI._build_source_settings
        )
        self.assertIn("Näytä tehtäväala:", source_ui)
        self.assertIn("Valitse näkyvät", source_ui)
        self.assertIn("Poista näkyvät", source_ui)

    def test_barona_is_removed_even_from_current_config_version(self):
        current = test_config()
        current["app"]["config_version"] = tyopaikkatutka.CONFIG_VERSION
        current["sources"] = [
            {
                "name": "Barona Helsinki",
                "type": "html",
                "url": "https://www.baronacareers.com/fi/fi/job/helsinki",
                "enabled": True,
            }
        ]
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        migrated, changed = tyopaikkatutka.merge_config_defaults(
            current,
            defaults,
        )
        self.assertTrue(changed)
        self.assertFalse(
            any(
                "barona" in source["name"].lower()
                for source in migrated["sources"]
            )
        )

    def test_broken_eezy_sitemap_is_migrated_and_enabled_choice_is_preserved(self):
        current = test_config()
        current["app"]["config_version"] = 7
        current["sources"] = [
            {
                "name": "Eezy",
                "type": "sitemap",
                "url": "https://tyopaikat.eezy.fi/fi",
                "sitemap_urls": ["https://tyopaikat.eezy.fi/sitemap.xml"],
                "enabled": True,
            }
        ]
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        migrated, changed = tyopaikkatutka.merge_config_defaults(
            current,
            defaults,
        )
        self.assertTrue(changed)
        self.assertEqual(8, migrated["app"]["config_version"])
        self.assertEqual("eezy", migrated["sources"][0]["type"])
        self.assertEqual(
            "https://api.eezy.fi/api",
            migrated["sources"][0]["api_url"],
        )
        self.assertTrue(migrated["sources"][0]["enabled"])

    def test_v13_broken_sources_are_migrated_but_enabled_choice_is_preserved(self):
        old = test_config()
        old["app"]["config_version"] = 3
        old["sources"] = [
            {
                "name": "Kuntarekry",
                "type": "sitemap",
                "url": "https://kuntarekry.fi/fi/tyopaikat/vantaa/",
                "sitemap_urls": ["https://kuntarekry.fi/sitemap.xml"],
                "enabled": True,
            },
            {
                "name": "Bolt.Works",
                "type": "sitemap",
                "url": "https://www.bolt.works/avoimet-tyopaikat/",
                "sitemap_urls": ["https://www.bolt.works/sitemap.xml"],
                "enabled": False,
            },
        ]
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        migrated, changed = tyopaikkatutka.merge_config_defaults(old, defaults)
        self.assertTrue(changed)
        by_name = {source["name"]: source for source in migrated["sources"]}
        self.assertEqual("feed", by_name["Kuntarekry"]["type"])
        self.assertIn("feed_urls", by_name["Kuntarekry"])
        self.assertEqual("sitemap", by_name["Bolt.Works"]["type"])
        self.assertIn(
            "https://laura.fi/sitemap_index.xml",
            by_name["Bolt.Works"]["sitemap_urls"],
        )
        self.assertFalse(by_name["Bolt.Works"]["enabled"])

    def test_fixed_default_sources_do_not_use_missing_sitemaps(self):
        defaults = json.loads(
            (
                Path(__file__).resolve().parents[1] / "config.default.json"
            ).read_text(encoding="utf-8")
        )
        by_name = {source["name"]: source for source in defaults["sources"]}
        for name in ("Kuntarekry", "Valtiolle.fi"):
            self.assertEqual("feed", by_name[name]["type"])
            self.assertTrue(by_name[name]["feed_urls"])
            self.assertFalse(
                any(url.endswith("/sitemap.xml") for url in by_name[name]["feed_urls"])
            )
        for name in ("Laura.fi – Uusimaa", "Helsinki Rekry", "Bolt.Works"):
            self.assertEqual("sitemap", by_name[name]["type"])
            self.assertEqual(
                ["https://laura.fi/sitemap_index.xml"],
                by_name[name]["sitemap_urls"],
            )

    def test_jsonld_parsing(self):
        _, detail_url = FakeHtmlClient().get_text("https://example.com/jobs/detail")
        raw, _ = FakeHtmlClient().get_text(detail_url)
        parser = tyopaikkatutka.parse_page(raw)
        objects = tyopaikkatutka.jsonld_job_objects(parser)
        self.assertEqual(1, len(objects))
        job = tyopaikkatutka.job_from_jsonld(
            objects[0], {"name": "Lähde"}, "https://example.com/jobs/detail"
        )
        self.assertEqual("Varastotyöntekijä", job.title)
        self.assertEqual("Testiyritys Oy", job.company)
        self.assertIn("Vantaa", job.location)
        self.assertEqual("Keräilyä ja pakkaamista.", job.description)

    def test_meta_without_name_or_property_does_not_crash(self):
        parser = tyopaikkatutka.parse_page(
            "<html><head><meta charset='utf-8'><meta><title>Testi</title></head>"
            "<body><h1>Varastotyöntekijä</h1></body></html>"
        )
        self.assertEqual("Testi", parser.title)
        self.assertEqual("Varastotyöntekijä", parser.h1)

    def test_workday_uses_single_locale_header(self):
        client = tyopaikkatutka.HttpClient()
        self.assertEqual("fi-FI", client.headers["Accept-Language"])
        self.assertNotIn(",", client.headers["Accept-Language"])

    def test_html_source_and_detail(self):
        source = {
            "name": "Testiyritys",
            "type": "html",
            "url": "https://example.com/jobs",
            "link_patterns": [r"example\.com/jobs/.+"],
            "enabled": True,
        }
        jobs = tyopaikkatutka.html_source_jobs(
            FakeHtmlClient(), source, test_config(), lambda message: None
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual("Varastotyöntekijä", jobs[0].title)
        self.assertEqual("2026-08-15", jobs[0].deadline)

    def test_workday_source(self):
        source = {
            "name": "Posti",
            "type": "workday",
            "url": "https://posti.wd3.myworkdayjobs.com/external",
        }
        client = FakeWorkdayClient()
        jobs = tyopaikkatutka.workday_source_jobs(
            client, source, test_config(), lambda message: None
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual("Pakkaaja", jobs[0].title)
        self.assertEqual("Vantaa", jobs[0].location)
        self.assertIn("Pakkaus-", jobs[0].description)
        self.assertLessEqual(client.post_payloads[0]["limit"], 20)

    def test_wordpress_source(self):
        source = {
            "name": "WorkPower",
            "type": "wordpress",
            "url": "https://www.workpower.fi/tyopaikat/",
            "api_url": "https://www.workpower.fi/wp-json/wp/v2/job",
        }
        jobs = tyopaikkatutka.wordpress_source_jobs(
            FakeWordPressClient(), source, test_config(), lambda message: None
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual("Varastotyöntekijä, Vantaa", jobs[0].title)
        self.assertEqual("Vantaa", jobs[0].location)
        self.assertEqual("15.8.2026", jobs[0].deadline)

    def test_eezy_source_uses_public_job_search_instead_of_sitemap(self):
        client = FakeEezyClient()
        source = {
            "name": "Eezy",
            "type": "eezy",
            "url": "https://tyopaikat.eezy.fi/fi",
            "api_url": "https://api.eezy.fi/api",
            "exclude_titles": ["avoin hakemus"],
            "api_page_size": 100,
            "maximum_api_jobs": 500,
        }
        jobs = tyopaikkatutka.eezy_source_jobs(
            client,
            source,
            test_config(),
            lambda _: None,
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual("Varastotyöntekijä, Vantaa", jobs[0].title)
        self.assertEqual("Varasto Oy", jobs[0].company)
        self.assertEqual("Vantaa, Uusimaa", jobs[0].location)
        self.assertEqual(
            "https://tyopaikat.eezy.fi/tyopaikat/job-101",
            jobs[0].url,
        )
        self.assertEqual("2099-08-15T20:59:59Z", jobs[0].deadline)
        self.assertEqual(
            "Keräilyä ja pakkaamista Vantaan varastossa.",
            jobs[0].description,
        )
        self.assertEqual(
            "https://api.eezy.fi/api",
            client.post_payloads[0][0],
        )

    def test_sitemap_source_keeps_expired_jobs_for_manual_removal(self):
        source = {
            "name": "Julkinen lähde",
            "type": "sitemap",
            "url": "https://example.com/jobs",
            "sitemap_urls": ["https://example.com/sitemap.xml"],
            "link_patterns": [r"example\.com/jobs/[^/?#]+-\d+$"],
        }
        jobs = tyopaikkatutka.sitemap_source_jobs(
            FakeSitemapClient(), source, test_config(), lambda message: None
        )
        self.assertEqual(2, len(jobs))
        self.assertEqual("Varastotyöntekijä", jobs[0].title)
        self.assertEqual("31.12.2099", jobs[0].deadline)
        self.assertEqual("2099-01-02", jobs[0].published)
        expired = next(job for job in jobs if job.title == "Siivooja")
        self.assertTrue(tyopaikkatutka.deadline_has_passed(expired.deadline))

    def test_feed_source_reads_rss_and_fetches_job_details(self):
        source = {
            "name": "Kuntarekry",
            "type": "feed",
            "url": "https://example.com/jobs",
            "feed_urls": ["https://example.com/jobs?format=rss"],
            "link_patterns": [r"example\.com/jobs/[^/?#]+-\d+$"],
            "exclude_titles": ["avoin hakemus"],
        }
        jobs = tyopaikkatutka.feed_source_jobs(
            FakeFeedClient(), source, test_config(), lambda message: None
        )
        self.assertEqual(1, len(jobs))
        self.assertEqual("Varastotyöntekijä", jobs[0].title)
        self.assertEqual("Kunnan Varasto Oy", jobs[0].company)
        self.assertIn("Vantaa", jobs[0].location)
        self.assertEqual("2099-12-31", jobs[0].deadline)

    def test_deadline_filter_only_rejects_dates_before_today(self):
        now = tyopaikkatutka.datetime(2026, 7, 30, 12, 0)
        self.assertTrue(tyopaikkatutka.deadline_has_passed("29.7.2026", now))
        self.assertFalse(tyopaikkatutka.deadline_has_passed("30.7.2026", now))
        self.assertFalse(tyopaikkatutka.deadline_has_passed("", now))

    def test_reopened_listing_requires_old_and_new_valid_deadlines(self):
        now = tyopaikkatutka.datetime(2026, 7, 30, 12, 0)
        previous = tyopaikkatutka.Job(
            title="Siivooja",
            company="Testi Oy",
            location="Helsinki",
            url="https://example.com/job",
            source="Testi",
            deadline="29.7.2026",
        )
        reopened = tyopaikkatutka.Job(
            title=previous.title,
            company=previous.company,
            location=previous.location,
            url=previous.url,
            source=previous.source,
            deadline="15.8.2026",
        )
        self.assertTrue(tyopaikkatutka.listing_has_reopened(previous, reopened, now))
        reopened.deadline = ""
        self.assertFalse(tyopaikkatutka.listing_has_reopened(previous, reopened, now))

    def test_cross_source_duplicates_are_merged(self):
        direct = tyopaikkatutka.Job(
            title="Varastotyöntekijä, Vantaa",
            company="WorkPower Oy",
            location="Vantaa",
            url="https://www.workpower.fi/tyopaikat/varastotyontekija-vantaa-1/",
            source="WorkPower",
            description="Varastotyötä.",
        )
        aggregator = tyopaikkatutka.Job(
            title="Varastotyöntekijä",
            company="WorkPower Palvelut Oy",
            location="Vantaa, Uusimaa",
            url=(
                "https://www.jobly.fi/tyopaikka/varastotyontekija-vantaa-123"
                "?utm_source=test"
            ),
            source="Jobly",
            description="Keräilyä, pakkaamista ja tavaran vastaanottoa.",
        )
        jobs = tyopaikkatutka.deduplicate_jobs([direct, aggregator])
        self.assertEqual(1, len(jobs))
        self.assertEqual(2, len(jobs[0].source_links()))
        self.assertTrue(jobs[0].url.startswith("https://www.workpower.fi/"))
        self.assertIn("WorkPower", jobs[0].source)
        self.assertIn("Jobly", jobs[0].source)

    def test_republished_jobs_far_apart_are_not_merged(self):
        first = tyopaikkatutka.Job(
            title="Varastotyöntekijä, Vantaa",
            company="Testi Oy",
            location="Vantaa",
            url="https://example.com/jobs/1",
            source="Yritys",
            published="2026-05-01",
        )
        second = tyopaikkatutka.Job(
            title="Varastotyöntekijä",
            company="Testi Oy",
            location="Vantaa, Uusimaa",
            url="https://example.com/jobs/2",
            source="Duunitori",
            published="24.07.2026",
        )
        self.assertEqual(2, len(tyopaikkatutka.deduplicate_jobs([first, second])))

    def test_good_job_scores_high(self):
        job = tyopaikkatutka.Job(
            title="Varastotyöntekijä",
            company="Testi Oy",
            location="Vantaa",
            url="https://example.com/1",
            source="Testi",
            description="Keräilyä, pakkaamista ja fyysistä varastotyötä.",
        )
        tyopaikkatutka.score_job(job, test_config())
        self.assertGreaterEqual(job.score, 65)
        self.assertIn("varastotyöntekijä", job.matched_roles)

    def test_missing_qualification_warns_and_penalizes(self):
        job = tyopaikkatutka.Job(
            title="Varastotyöntekijä",
            company="Testi Oy",
            location="Vantaa",
            url="https://example.com/2",
            source="Testi",
            description="Tehtävässä vaaditaan voimassa oleva trukkikortti.",
        )
        tyopaikkatutka.score_job(job, test_config())
        self.assertTrue(any("puuttuvan pätevyyden" in item for item in job.warnings))
        self.assertLess(job.score, 65)

    def test_excluded_commission_is_penalized(self):
        job = tyopaikkatutka.Job(
            title="Varastotyöntekijä",
            company="Testi Oy",
            location="Vantaa",
            url="https://example.com/3",
            source="Testi",
            description="Työssä on pelkkä provisiopalkka.",
        )
        tyopaikkatutka.score_job(job, test_config())
        self.assertTrue(any("Ei-toivottu ehto" in item for item in job.warnings))

    def test_database_prevents_duplicates_and_preserves_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "jobs.db"
            database = tyopaikkatutka.JobDatabase(db_path)
            try:
                job = tyopaikkatutka.Job(
                    title="Siivooja",
                    company="Testi Oy",
                    location="Helsinki",
                    url="https://example.com/job",
                    source="Testi",
                    score=70,
                )
                self.assertTrue(database.upsert(job))
                database.set_status(job.fingerprint, "applied")
                job.score = 75
                self.assertFalse(database.upsert(job))
                self.assertEqual(1, database.count())
                row = database.get_job(job.fingerprint)
                self.assertEqual("applied", row["status"])
                self.assertEqual(75, row["score"])
                self.assertIsNone(row["draft"])
            finally:
                database.close()

    def test_expired_job_stays_visible_until_manually_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = tyopaikkatutka.JobDatabase(Path(temp_dir) / "jobs.db")
            try:
                expired = tyopaikkatutka.Job(
                    title="Siivooja",
                    company="Testi Oy",
                    location="Helsinki",
                    url="https://example.com/expired",
                    source="Testi",
                    deadline="1.1.2000",
                    score=70,
                )
                database.upsert(expired)
                database.connection.execute(
                    "UPDATE jobs SET last_seen = ? WHERE fingerprint = ?",
                    ("2000-01-01T00:00:00", expired.fingerprint),
                )
                database.connection.commit()

                visible = database.list_jobs(minimum_score=0, days=60)
                self.assertEqual([expired.fingerprint], [row["fingerprint"] for row in visible])

                database.set_status(expired.fingerprint, "ignored")
                self.assertEqual([], database.list_jobs(minimum_score=0, days=60))
                removed = database.list_jobs(
                    minimum_score=0,
                    days=60,
                    include_ignored=True,
                )
                self.assertEqual("ignored", removed[0]["status"])
            finally:
                database.close()

    def test_removed_expired_job_returns_as_republished_with_new_deadline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = tyopaikkatutka.JobDatabase(Path(temp_dir) / "jobs.db")
            try:
                expired = tyopaikkatutka.Job(
                    title="Varastotyöntekijä",
                    company="Testi Oy",
                    location="Vantaa",
                    url="https://example.com/reused-job",
                    source="Testi",
                    description="Varastotyötä.",
                    deadline="1.1.2000",
                    published="1.12.1999",
                    score=70,
                )
                database.upsert(expired)
                database.set_status(expired.fingerprint, "ignored")

                reopened = tyopaikkatutka.Job(
                    title=expired.title,
                    company=expired.company,
                    location=expired.location,
                    url=expired.url,
                    source=expired.source,
                    description="Varastotyötä uudella hakuajalla.",
                    deadline="31.12.2099",
                    published="1.12.2099",
                    score=75,
                )
                self.assertTrue(database.upsert(reopened))

                row = database.get_job(expired.fingerprint)
                self.assertEqual("republished", row["status"])
                self.assertEqual("31.12.2099", row["deadline"])
                self.assertEqual("1.12.2099", row["published"])
                visible = database.list_jobs(minimum_score=0, days=60)
                self.assertEqual([expired.fingerprint], [item["fingerprint"] for item in visible])

                # Sama uusi hakuaika ei saa tuottaa ilmoitusta uudelleen.
                self.assertFalse(database.upsert(reopened))
                self.assertEqual("republished", database.get_job(expired.fingerprint)["status"])
            finally:
                database.close()

    def test_reopening_does_not_replace_existing_applied_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = tyopaikkatutka.JobDatabase(Path(temp_dir) / "jobs.db")
            try:
                expired = tyopaikkatutka.Job(
                    title="Pakkaaja",
                    company="Testi Oy",
                    location="Vantaa",
                    url="https://example.com/applied-job",
                    source="Testi",
                    deadline="1.1.2000",
                    score=70,
                )
                database.upsert(expired)
                database.set_status(expired.fingerprint, "applied")
                reopened = tyopaikkatutka.Job(
                    title=expired.title,
                    company=expired.company,
                    location=expired.location,
                    url=expired.url,
                    source=expired.source,
                    deadline="31.12.2099",
                    score=75,
                )
                self.assertFalse(database.upsert(reopened))
                row = database.get_job(expired.fingerprint)
                self.assertEqual("applied", row["status"])
                self.assertEqual("31.12.2099", row["deadline"])
            finally:
                database.close()

    def test_expired_job_is_stored_but_not_announced_as_new(self):
        config = test_config()
        config["sources"] = [
            {
                "name": "Päättynyt lähde",
                "type": "html",
                "url": "https://example.com/jobs",
                "enabled": True,
            }
        ]
        expired = tyopaikkatutka.Job(
            title="Varastotyöntekijä",
            company="Testi Oy",
            location="Vantaa",
            url="https://example.com/expired-job",
            source="Päättynyt lähde",
            description="Keräilyä ja pakkaamista.",
            deadline="1.1.2000",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scanner = tyopaikkatutka.JobScanner(
                config,
                progress=lambda message: None,
                database_path=root / "jobs.db",
            )
            with (
                mock.patch.object(tyopaikkatutka, "html_source_jobs", return_value=[expired]),
                mock.patch.object(tyopaikkatutka, "REPORT_DIR", root / "raportit"),
            ):
                result = scanner.scan()
            self.assertEqual(1, result.found_count)
            self.assertEqual(1, result.stored_count)
            self.assertEqual([], result.new_matches)

    def test_database_migrates_v11_and_preserves_applied_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "jobs.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE jobs (
                    fingerprint TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    source TEXT,
                    description TEXT,
                    deadline TEXT,
                    published TEXT,
                    score INTEGER NOT NULL DEFAULT 0,
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    matched_roles_json TEXT NOT NULL DEFAULT '[]',
                    draft TEXT,
                    status TEXT NOT NULL DEFAULT 'new',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    fingerprint, url, title, company, location, source,
                    description, score, draft, status, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "old-fingerprint",
                    "https://www.workpower.fi/tyopaikat/varastotyontekija-vantaa-1/",
                    "Varastotyöntekijä, Vantaa",
                    "WorkPower Oy",
                    "Vantaa",
                    "WorkPower",
                    "Vanha ilmoitus",
                    70,
                    "Vanha luonnos",
                    "applied",
                    "2026-07-26T10:00:00",
                    "2026-07-26T10:00:00",
                ),
            )
            connection.commit()
            connection.close()

            with mock.patch.object(tyopaikkatutka, "BACKUP_DIR", root / "varmuuskopiot"):
                database = tyopaikkatutka.JobDatabase(db_path)
                try:
                    row = database.get_job("old-fingerprint")
                    self.assertEqual("applied", row["status"])
                    self.assertTrue(row["canonical_key"])
                    self.assertEqual(1, len(json.loads(row["links_json"])))

                    duplicate = tyopaikkatutka.Job(
                        title="Varastotyöntekijä",
                        company="WorkPower Palvelut Oy",
                        location="Vantaa, Uusimaa",
                        url="https://www.jobly.fi/tyopaikka/varastotyontekija-123",
                        source="Jobly",
                        score=75,
                    )
                    self.assertFalse(database.upsert(duplicate))
                    self.assertEqual(1, database.count())
                    row = database.get_job("old-fingerprint")
                    self.assertEqual("applied", row["status"])
                    self.assertEqual("Vanha luonnos", row["draft"])
                    self.assertEqual(2, len(json.loads(row["links_json"])))
                finally:
                    database.close()

    def test_end_to_end_scan_creates_match_and_report(self):
        config = test_config()
        config["sources"] = [
            {
                "name": "Testiyritys",
                "type": "html",
                "url": "https://example.com/jobs",
                "link_patterns": [r"example\.com/jobs/.+"],
                "enabled": True,
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scanner = tyopaikkatutka.JobScanner(
                config,
                progress=lambda message: None,
                database_path=root / "jobs.db",
            )
            scanner.client = FakeHtmlClient()
            with mock.patch.object(tyopaikkatutka, "REPORT_DIR", root / "raportit"):
                result = scanner.scan()
            self.assertEqual(1, result.found_count)
            self.assertEqual(1, len(result.new_matches))
            self.assertTrue(result.report_path.exists())
            self.assertIn(
                "Varastotyöntekijä",
                result.report_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                [],
                list((root / "raportit").glob("hakemus_*.txt")),
            )

    def test_real_config_is_valid_json(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ("config.json", "config.default.json"):
            loaded = json.loads((root / filename).read_text(encoding="utf-8"))
            self.assertIn("sources", loaded)
            self.assertGreaterEqual(len(loaded["sources"]), 9)


if __name__ == "__main__":
    unittest.main()
