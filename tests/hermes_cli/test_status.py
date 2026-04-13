from types import SimpleNamespace

from hermes_cli.status import show_status


def test_show_status_includes_tavily_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-1234567890abcdef")

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "Tavily" in output
    assert "tvly...cdef" in output


def test_show_status_termux_gateway_section_skips_systemctl(monkeypatch, capsys, tmp_path):
    from hermes_cli import status as status_mod
    import hermes_cli.auth as auth_mod
    import hermes_cli.gateway as gateway_mod

    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(status_mod, "get_env_path", lambda: tmp_path / ".env", raising=False)
    monkeypatch.setattr(status_mod, "get_hermes_home", lambda: tmp_path, raising=False)
    monkeypatch.setattr(status_mod, "load_config", lambda: {"model": "gpt-5.4"}, raising=False)
    monkeypatch.setattr(status_mod, "resolve_requested_provider", lambda requested=None: "openai-codex", raising=False)
    monkeypatch.setattr(status_mod, "resolve_provider", lambda requested=None, **kwargs: "openai-codex", raising=False)
    monkeypatch.setattr(status_mod, "provider_label", lambda provider: "OpenAI Codex", raising=False)
    monkeypatch.setattr(auth_mod, "get_nous_auth_status", lambda: {}, raising=False)
    monkeypatch.setattr(auth_mod, "get_codex_auth_status", lambda: {}, raising=False)
    monkeypatch.setattr(gateway_mod, "find_gateway_pids", lambda exclude_pids=None: [], raising=False)

    def _unexpected_systemctl(*args, **kwargs):
        raise AssertionError("systemctl should not be called in the Termux status view")

    monkeypatch.setattr(status_mod.subprocess, "run", _unexpected_systemctl)

    status_mod.show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "Manager:      Termux / manual process" in output
    assert "Start with:   hermes gateway" in output
    assert "systemd (user)" not in output


def test_show_status_includes_vision_runtime_defaults(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "◆ Vision Runtime" in output
    assert "Download timeout:       30s (default)" in output
    assert "Error warn threshold:   3 (default)" in output
    assert "Remote image timeout:   20s (default)" in output
    assert "Remote cache ttl:       180s (default)" in output
    assert "Remote cache entries:   96 (default)" in output


def test_show_status_vision_runtime_prefers_env(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_VISION_DOWNLOAD_TIMEOUT", "41")
    monkeypatch.setenv("HERMES_VISION_ERROR_WARN_THRESHOLD", "9")
    monkeypatch.setenv("HERMES_VERTEX_REMOTE_IMAGE_TIMEOUT_SECONDS", "13")
    monkeypatch.setenv("HERMES_VERTEX_REMOTE_IMAGE_CACHE_TTL_SECONDS", "99")
    monkeypatch.setenv("HERMES_VERTEX_REMOTE_IMAGE_CACHE_MAX_ENTRIES", "17")

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "Download timeout:       41s (env)" in output
    assert "Error warn threshold:   9 (env)" in output
    assert "Remote image timeout:   13s (env)" in output
    assert "Remote cache ttl:       99s (env)" in output
    assert "Remote cache entries:   17 (env)" in output


def test_show_status_vision_runtime_deep_no_anomalies(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    show_status(SimpleNamespace(all=False, deep=True))

    output = capsys.readouterr().out
    assert "◆ Vision Runtime" in output
    assert "Deep diagnostics: no anomalies detected" in output


def test_show_status_vision_runtime_deep_warns_on_invalid_values(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        (
            "auxiliary:\n"
            "  vision:\n"
            "    download_timeout: -1\n"
            "    error_warn_threshold: 0\n"
            "    remote_image_timeout: abc\n"
            "    remote_image_cache_ttl: -5\n"
            "    remote_image_cache_max_entries: 0\n"
        ),
        encoding="utf-8",
    )

    show_status(SimpleNamespace(all=False, deep=True))

    output = capsys.readouterr().out
    assert "download_timeout ignored" in output
    assert "error_warn_threshold ignored" in output
    assert "remote_image_timeout ignored" in output
    assert "remote_image_cache_ttl ignored" in output
    assert "remote_image_cache_max_entries ignored" in output
