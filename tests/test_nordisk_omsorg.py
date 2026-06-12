"""nordisk-omsorg instance: compute units, planted hallucination, offline e2e."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]


def load_instance():
    spec = importlib.util.spec_from_file_location(
        "nordisk_stages", REPO / "analyses" / "nordisk-omsorg" / "stages.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSqueezeTable:
    def small(self) -> pd.DataFrame:
        return pd.DataFrame({
            "geo_id": ["NO-0001", "NO-0002", "NO-0003", "NO-0004"],
            "geo_name": ["A", "B", "C", "D"],
            "coverage": [40.0, 30.0, 20.0, 10.0],
            "elderly_base": [100, 100, 100, 100],
            "elderly_latest": [100, 110, 120, 130],
        })

    def test_squeeze_orders_low_coverage_high_growth_first(self) -> None:
        mod = load_instance()
        out = mod.squeeze_table(self.small())
        assert out.sort_values("rank")["geo_name"].tolist() == ["D", "C", "B", "A"]
        assert out["growth_pct"].round(1).tolist() == [30.0, 20.0, 10.0, 0.0]

    def test_zero_std_gives_zero_z(self) -> None:
        mod = load_instance()
        df = self.small().assign(coverage=25.0)
        out = mod.squeeze_table(df)
        assert (out["z_coverage"] == 0).all()

    def test_missing_rows_dropped_and_counted(self) -> None:
        mod = load_instance()
        df = self.small()
        df.loc[0, "coverage"] = np.nan
        out = mod.squeeze_table(df)
        assert len(out) == 3
        assert out.attrs["n_dropped"] == 1


class TestFindings:
    def tables(self) -> dict[str, pd.DataFrame]:
        mod = load_instance()
        base = TestSqueezeTable().small()
        return {
            "NO": mod.squeeze_table(base),
            "SE": mod.squeeze_table(base.assign(
                geo_id=["SE-0001", "SE-0002", "SE-0003", "SE-0004"])),
        }

    def test_findings_shape_and_schema(self) -> None:
        mod = load_instance()
        from omsorgsradar.core.contracts import validate_artifact
        findings = mod.findings_from_tables(
            self.tables(), params={"base_year": 2019, "latest_year": 2023, "top_n": 2},
            context={},
        )
        validate_artifact("nordic_findings", findings)
        no = findings["countries"]["NO"]
        assert no["n_municipalities"] == 4
        assert no["coverage_median"] == 25.0
        assert len(no["top_squeeze"]) == 2
        assert no["top_squeeze"][0]["geo_name"] == "D"
        assert findings["analysis_years"] == {"base": 2019, "latest": 2023}

    def test_high_squeeze_share(self) -> None:
        mod = load_instance()
        f = mod.findings_from_tables(
            self.tables(), params={"base_year": 2019, "latest_year": 2023, "top_n": 2},
            context={},
        )
        assert f["countries"]["NO"]["high_squeeze_share"] == 0.5


def _fixture_datasets() -> dict[str, pd.DataFrame]:
    """Build the ingest-stage output by running the REAL adapters against the
    committed fixtures through a seeded cache (no network)."""
    import shutil
    import tempfile

    from omsorgsradar.core.adapters import make_adapter
    from omsorgsradar.core.config import load_run_config

    tmp = Path(tempfile.mkdtemp())
    fx = REPO / "tests" / "fixtures"
    seeds = {
        "nordisk_no_kostra_12209.json": "ssb_12209_g2_fixture.json",
        "nordisk_no_befolkning_07459.json": "ssb_07459_g2_fixture.json",
        "nordisk_se_befolkning.json": "scb_befolkning_fixture.json",
        "sotkanet_regions.json": "sotkanet_regions_fixture.json",
        "sotkanet_5513_2023_total.json": "sotkanet_5513_fixture.json",
        "sotkanet_171_2019-2023_total.json": "sotkanet_171_fixture.json",
        "sotkanet_127_2019-2023_total.json": "sotkanet_127_g2_fixture.json",
        "kolada_municipalities.json": "kolada_municipalities_fixture.json",
        "kolada_N21704_2023.json": "kolada_n21704_fixture.json",
        "kuhr_LE_2019_2023_t2ad.json": "kuhr_le_2ad_g2_fixture.json",
    }
    for cache_name, fixture_name in seeds.items():
        shutil.copy(fx / fixture_name, tmp / cache_name)
    cfg = load_run_config(REPO / "analyses" / "nordisk-omsorg", REPO / "workflow.toml")
    return {
        src["id"]: make_adapter(
            src, cache_dir=tmp, base_dir=cfg.analysis_dir
        ).fetch(src)
        for src in cfg.sources
    }


class TestCountryTables:
    def test_build_country_tables_from_fixtures(self) -> None:
        mod = load_instance()
        datasets = _fixture_datasets()
        tables = mod.build_country_tables(
            datasets, params={"base_year": 2019, "latest_year": 2023}
        )
        assert set(tables) == {"NO", "SE", "FI"}
        for country, t in tables.items():
            assert len(t) >= 3, country
            assert t["geo_id"].str.startswith(country).all()
        no = tables["NO"]
        assert "NO-1505" in set(no["geo_id"])
        assert "Kristiansund" in " ".join(no["geo_name"].tolist())

    def test_no_names_have_no_era_suffix_and_growth_is_sane(self) -> None:
        mod = load_instance()
        tables = mod.build_country_tables(
            _fixture_datasets(), params={"base_year": 2019, "latest_year": 2023}
        )
        no = mod.squeeze_table(tables["NO"])
        assert not no["geo_name"].str.contains(r"\(\d{4}", regex=True).any()
        # with the KLASS-rebuilt merger map, 80+ growth artifacts are gone:
        assert no["growth_pct"].max() < 60, no.nlargest(5, "growth_pct")[
            ["geo_id", "geo_name", "growth_pct"]
        ]
        assert len(no) > 300   # full mapping connects most 2019 series


class TestNordiskVerify:
    def _run_analyze(self, tmp_path: Path):
        from omsorgsradar.core.config import load_run_config
        from omsorgsradar.core.journal import RunJournal
        from omsorgsradar.core.registry import StageContext

        mod = load_instance()
        cfg = load_run_config(REPO / "analyses" / "nordisk-omsorg",
                              REPO / "workflow.toml")
        journal = RunJournal.start(tmp_path / "runs", analysis="nordisk-omsorg",
                                   config_snapshot={})
        ctx = StageContext(config=cfg, data_dir=tmp_path,
                           reports_dir=tmp_path / "reports", journal=journal)
        ctx.state["datasets"] = _fixture_datasets()
        mod.stage_analyze_nordisk(ctx)
        return mod, ctx

    def test_verify_passes_on_honest_findings(self, tmp_path: Path) -> None:
        import json as _json
        mod, ctx = self._run_analyze(tmp_path)
        mod.stage_verify_nordisk(ctx)
        v = _json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
        assert v["verdict"] == "PASS"
        assert v["failed"] == 0
        assert v["total_claims"] >= 40  # 3 countries × (5 stats + top_n×5) + comparison

    def test_planted_hallucination_caught(self, tmp_path: Path) -> None:
        import json as _json
        from omsorgsradar.core.registry import PipelineGateError

        mod, ctx = self._run_analyze(tmp_path)
        f_path = tmp_path / "nordic_findings.json"
        findings = _json.loads(f_path.read_text(encoding="utf-8"))
        findings["countries"]["NO"]["coverage_median"] += 7.7   # plant the lie
        findings["countries"]["NO"]["top_squeeze"][0]["geo_id"] = "NO-9999"
        f_path.write_text(_json.dumps(findings, ensure_ascii=False),
                          encoding="utf-8")
        ctx.state["nordic_findings"] = findings
        with pytest.raises(PipelineGateError):
            mod.stage_verify_nordisk(ctx)
        v = _json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
        assert v["verdict"] == "FAIL"
        assert v["failed"] >= 2


class TestNordiskReport:
    def test_report_renders_from_findings_only(self, tmp_path: Path) -> None:
        mod, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        mod.stage_verify_nordisk(ctx)
        mod.stage_report_nordisk(ctx)
        report = (tmp_path / "reports" / "nordisk-omsorg_rapport.md").read_text(
            encoding="utf-8"
        )
        f = ctx.state["nordic_findings"]
        assert "deskriptiv, ikke kausal" in report
        assert "75+" in report and "80+" in report
        for country in ("NO", "SE", "FI"):
            assert f["countries"][country]["top_squeeze"][0]["geo_name"] in report
            assert str(f["countries"][country]["coverage_median"]) in report
        comp = f["comparison"]["lowest_high_squeeze_share_country"]
        comp_nb = {"NO": "Norge", "SE": "Sverige", "FI": "Finland"}[comp]
        assert comp_nb in report
        figs = list((tmp_path / "reports" / "figures").glob("nordisk_*.png"))
        assert len(figs) == 3

    def test_report_refuses_without_green_verification(self, tmp_path: Path) -> None:
        from omsorgsradar.core.registry import PipelineGateError
        mod, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        with pytest.raises(PipelineGateError):
            mod.stage_report_nordisk(ctx)


class TestRegister:
    def test_register_shadows_three_stages(self) -> None:
        from omsorgsradar.stages import build_default_registry

        mod = load_instance()
        reg = build_default_registry()
        mod.register(reg)
        assert reg.get("analyze") is mod.stage_analyze_nordisk
        assert reg.get("verify") is mod.stage_verify_nordisk
        assert reg.get("report") is mod.stage_report_nordisk
        assert reg.get("ingest") is not None


class TestNordiskE2E:
    def test_full_offline_pipeline(self, tmp_path: Path) -> None:
        import json as _json
        import shutil

        from omsorgsradar.pipeline import run_pipeline

        data_dir = tmp_path / "data"
        cache = data_dir / "cache"
        cache.mkdir(parents=True)
        fx = REPO / "tests" / "fixtures"
        seeds = {
            "nordisk_no_kostra_12209.json": "ssb_12209_g2_fixture.json",
            "nordisk_no_befolkning_07459.json": "ssb_07459_g2_fixture.json",
            "nordisk_se_befolkning.json": "scb_befolkning_fixture.json",
            "sotkanet_regions.json": "sotkanet_regions_fixture.json",
            "sotkanet_5513_2023_total.json": "sotkanet_5513_fixture.json",
            "sotkanet_171_2019-2023_total.json": "sotkanet_171_fixture.json",
            "sotkanet_127_2019-2023_total.json": "sotkanet_127_g2_fixture.json",
            "kolada_municipalities.json": "kolada_municipalities_fixture.json",
            "kolada_N21704_2023.json": "kolada_n21704_fixture.json",
            "kuhr_LE_2019_2023_t2ad.json": "kuhr_le_2ad_g2_fixture.json",
        }
        for cache_name, fixture_name in seeds.items():
            shutil.copy(fx / fixture_name, cache / cache_name)

        report = run_pipeline(
            REPO / "analyses" / "nordisk-omsorg",
            data_dir=data_dir,
            reports_dir=tmp_path / "reports",
            runs_dir=tmp_path / "runs",
        )
        assert report is not None and report.exists()

        v = _json.loads((data_dir / "verification.json").read_text(encoding="utf-8"))
        assert v["verdict"] == "PASS" and v["failed"] == 0

        q = _json.loads((data_dir / "quality_profile.json").read_text(encoding="utf-8"))
        for sid in ("no_kostra", "se_hemtjanst", "fi_homecare"):
            assert q["datasets"][sid]["realness"]["verdict"] in ("PASS", "WARN"), sid

        run_files = list((tmp_path / "runs").glob("*/run.json"))
        assert len(run_files) == 1
        run = _json.loads(run_files[0].read_text(encoding="utf-8"))
        assert run["status"] == "ok"


class TestNordiskPerCountryGuard:
    """B2: empty country frame raises PipelineGateError naming country + source."""

    def _make_ctx(self, tmp_path: Path, doctored_datasets: dict):
        from omsorgsradar.core.config import load_run_config
        from omsorgsradar.core.journal import RunJournal
        from omsorgsradar.core.registry import StageContext

        cfg = load_run_config(REPO / "analyses" / "nordisk-omsorg",
                              REPO / "workflow.toml")
        journal = RunJournal.start(tmp_path / "runs", analysis="nordisk-omsorg",
                                   config_snapshot={})
        ctx = StageContext(config=cfg, data_dir=tmp_path,
                           reports_dir=tmp_path / "reports", journal=journal)
        ctx.state["datasets"] = doctored_datasets
        return ctx

    def _base_datasets(self):
        return _fixture_datasets()

    def test_empty_fi_table_raises_gate_error(self, tmp_path: Path) -> None:
        """Doctoring fi_homecare to be empty causes stage_analyze to raise."""
        from omsorgsradar.core.registry import PipelineGateError

        mod = load_instance()
        datasets = self._base_datasets()
        # Doctor FI homecare dataset to be empty
        datasets["fi_homecare"] = datasets["fi_homecare"].iloc[0:0]
        ctx = self._make_ctx(tmp_path, datasets)

        with pytest.raises(PipelineGateError, match="FI"):
            mod.stage_analyze_nordisk(ctx)

    def test_empty_se_table_raises_gate_error(self, tmp_path: Path) -> None:
        """Doctoring se_hemtjanst to be empty causes stage_analyze to raise."""
        from omsorgsradar.core.registry import PipelineGateError

        mod = load_instance()
        datasets = self._base_datasets()
        datasets["se_hemtjanst"] = datasets["se_hemtjanst"].iloc[0:0]
        ctx = self._make_ctx(tmp_path, datasets)

        with pytest.raises(PipelineGateError, match="SE"):
            mod.stage_analyze_nordisk(ctx)

    def test_gate_error_names_country_and_source(self, tmp_path: Path) -> None:
        """The error message includes the country code and source identifiers."""
        from omsorgsradar.core.registry import PipelineGateError

        mod = load_instance()
        datasets = self._base_datasets()
        datasets["no_kostra"] = datasets["no_kostra"].iloc[0:0]
        ctx = self._make_ctx(tmp_path, datasets)

        with pytest.raises(PipelineGateError) as exc_info:
            mod.stage_analyze_nordisk(ctx)
        msg = str(exc_info.value)
        assert "NO" in msg
        assert "no_kostra" in msg

    def test_report_stage_rejects_empty_country_frame(self, tmp_path: Path) -> None:
        """stage_report_nordisk raises when a country frame is empty in the CSV."""
        import json as _json
        import shutil

        from omsorgsradar.core.config import load_run_config
        from omsorgsradar.core.journal import RunJournal
        from omsorgsradar.core.registry import PipelineGateError, StageContext

        mod = load_instance()
        # Run analyze successfully first
        m, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        m.stage_verify_nordisk(ctx)

        # Now overwrite nordic_table.csv with SE rows removed
        table_path = tmp_path / "nordic_table.csv"
        table = pd.read_csv(table_path)
        table = table[table["country"] != "SE"]
        table.to_csv(table_path, index=False)

        with pytest.raises(PipelineGateError, match="SE"):
            m.stage_report_nordisk(ctx)


class TestNordiskTextFixes:
    """B1: verify nb-style formatting and corrected grammar in the report."""

    def test_report_uses_deskriptiv_ikke_kausal(self, tmp_path: Path) -> None:
        m, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        m.stage_verify_nordisk(ctx)
        m.stage_report_nordisk(ctx)
        report = (tmp_path / "reports" / "nordisk-omsorg_rapport.md").read_text(
            encoding="utf-8"
        )
        assert "deskriptiv, ikke kausal" in report
        assert "deskriptivt, ikke kausalt" not in report

    def test_report_gloss_kontroller(self, tmp_path: Path) -> None:
        m, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        m.stage_verify_nordisk(ctx)
        m.stage_report_nordisk(ctx)
        report = (tmp_path / "reports" / "nordisk-omsorg_rapport.md").read_text(
            encoding="utf-8"
        )
        # The gloss clause should appear after "kontroller OK"
        assert "én uavhengig omregning per rangert kommune" in report
