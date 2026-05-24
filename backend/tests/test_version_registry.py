from app.search.version_registry import extract_year_from_filename, VersionRegistry


class TestExtractYear:
    def test_4digit_year(self):
        assert extract_year_from_filename("bwl-2024-ps00.pdf") == 2024

    def test_4digit_year_amendment(self):
        assert extract_year_from_filename("bwl-2024-ps01.pdf") == 2024

    def test_2digit_year(self):
        assert extract_year_from_filename("1574-08-ps00.pdf") == 2008

    def test_2digit_year_old(self):
        assert extract_year_from_filename("xyz-98-ps00.pdf") == 1998

    def test_embedded_year(self):
        assert extract_year_from_filename("1574-16in-ma2012-ps00.pdf") == 2012

    def test_no_year(self):
        assert extract_year_from_filename("no-year-here.pdf") is None

    def test_complex_filename(self):
        assert extract_year_from_filename("1577-16in-nf30ma-2022-ps00.pdf") == 2022


class TestVersionRegistry:
    def test_build_from_manifest(self, mock_manifest):
        registry = VersionRegistry.build_from_manifest(mock_manifest)

        # BWL: 2024 is newest → 2018 blocked, 2024 ps00 allowed, 2024 ps01 allowed, 2020 ps01 blocked
        assert registry.is_allowed("bwl-2024-ps00.pdf")
        assert registry.is_allowed("bwl-2024-ps01.pdf")
        assert not registry.is_allowed("bwl-2018-ps00.pdf")
        assert not registry.is_allowed("bwl-2020-ps01.pdf")

    def test_informatik_allowed(self, mock_manifest):
        registry = VersionRegistry.build_from_manifest(mock_manifest)

        assert registry.is_allowed("info-2022-ps00.pdf")
        assert registry.is_allowed("info-2022-ps01.pdf")

    def test_eignung_zulassung_always_allowed(self, mock_manifest):
        registry = VersionRegistry.build_from_manifest(mock_manifest)

        assert registry.is_allowed("info-eignung-2022.pdf")
        assert registry.is_allowed("info-zulassung-2019.pdf")

    def test_unknown_file_allowed(self, mock_manifest):
        registry = VersionRegistry.build_from_manifest(mock_manifest)
        assert registry.is_allowed("unknown-file.pdf")

    def test_blocked_filenames(self, mock_manifest):
        registry = VersionRegistry.build_from_manifest(mock_manifest)
        blocked = registry.get_blocked_filenames()

        assert "bwl-2018-ps00.pdf" in blocked
        assert "bwl-2020-ps01.pdf" in blocked
        assert "bwl-2024-ps00.pdf" not in blocked
