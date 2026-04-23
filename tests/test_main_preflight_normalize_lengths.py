from __future__ import annotations


from click.testing import CliRunner


def test_main_preflights_normalize_lengths_for_guest_only_action(monkeypatch):
    import main as main_module

    normalized_calls: list[tuple[str, str]] = []
    execute_calls: list[tuple[str, str, dict[str, object]]] = []
    build_pipeline_called = False

    def fake_normalize_video_lengths(host: str, guest: str) -> tuple[str, str]:
        normalized_calls.append((host, guest))
        return "H_norm.mp4", "G_norm.mp4"

    class _FakePipeline:
        def execute(self, host: str, guest: str, **kwargs):
            execute_calls.append((host, guest, kwargs))
            return "host_out.mp4", "guest_out.mp4"

    def fake_build_pipeline(config: dict):
        nonlocal build_pipeline_called
        build_pipeline_called = True
        return _FakePipeline()

    monkeypatch.setattr(main_module, "normalize_video_lengths", fake_normalize_video_lengths)
    monkeypatch.setattr(main_module, "_build_pipeline", fake_build_pipeline)

    runner = CliRunner()
    result = runner.invoke(
        main_module.main,
        [
            "--host",
            "H.mp4",
            "--guest",
            "G.mp4",
        ],
    )
    assert result.exit_code == 0, result.output
    assert normalized_calls == [("H.mp4", "G.mp4")]
    assert build_pipeline_called is True
    assert len(execute_calls) == 1

    host, guest, kwargs = execute_calls[0]
    assert (host, guest) == ("H_norm.mp4", "G_norm.mp4")
    assert kwargs == {}


def test_main_preflights_normalize_lengths_for_all_action(monkeypatch):
    import main as main_module

    normalized_calls: list[tuple[str, str]] = []
    execute_calls: list[tuple[str, str, dict[str, object]]] = []
    build_pipeline_called = False

    def fake_normalize_video_lengths(host: str, guest: str) -> tuple[str, str]:
        normalized_calls.append((host, guest))
        return "H_norm.mp4", "G_norm.mp4"

    class _FakePipeline:
        def execute(self, host: str, guest: str, **kwargs):
            execute_calls.append((host, guest, kwargs))
            return "host_out.mp4", "guest_out.mp4"

    def fake_build_pipeline(config: dict):
        nonlocal build_pipeline_called
        build_pipeline_called = True
        return _FakePipeline()

    monkeypatch.setattr(main_module, "normalize_video_lengths", fake_normalize_video_lengths)
    monkeypatch.setattr(main_module, "_build_pipeline", fake_build_pipeline)

    runner = CliRunner()
    result = runner.invoke(
        main_module.main,
        [
            "--host",
            "H.mp4",
            "--guest",
            "G.mp4",
        ],
    )
    assert result.exit_code == 0, result.output

    assert normalized_calls == [("H.mp4", "G.mp4")]
    assert build_pipeline_called is True
    assert len(execute_calls) == 1

    host, guest, kwargs = execute_calls[0]
    assert (host, guest) == ("H_norm.mp4", "G_norm.mp4")
    assert kwargs == {}
