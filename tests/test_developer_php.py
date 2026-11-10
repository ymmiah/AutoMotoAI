"""Developer Studio V16: PHP/Composer/WordPress security, real plugin patch and agent linkage."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_php as php, sandbox, server
from automoto.hosted import path_allowed

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}
BASE="/api/developer/studio/php"
PLUGIN="""<?php
/*
Plugin Name: Reviewable Notice
Version: 1.0.0
Requires PHP: 8.1
Text Domain: reviewable-notice
*/
add_action( 'admin_notices', 'reviewable_notice' );
add_filter( 'the_content', 'reviewable_content' );
register_activation_hook( __FILE__, 'reviewable_activate' );
function reviewable_activate() {
    update_option( 'reviewable_enabled', true );
}
function reviewable_content( $content ) {
    return $content;
}
function reviewable_notice() {
    echo $_GET['notice'];
}
"""
COMPOSER={"name":"example/reviewable-notice","type":"wordpress-plugin",
          "require":{"php":">=8.1","symfony/console":"^7.0"},
          "require-dev":{"phpunit/phpunit":"^11.0","phpstan/phpstan":"^2.0"},
          "scripts":{"test":"phpunit","post-install-cmd":"echo never execute automatically"}}

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    root=sandbox.default_root()/"v16-wp-plugin"
    root.mkdir(parents=True)
    (root/"reviewable-notice.php").write_text(PLUGIN,encoding="utf-8")
    (root/"composer.json").write_text(json.dumps(COMPOSER),encoding="utf-8")
    (root/"composer.lock").write_text('{"packages":[],"packages-dev":[]}',encoding="utf-8")
    return TestClient(server.app),root

def inspect(client,root):
    return client.get(BASE+"/inspect",headers=AUTH,params={"project":str(root)})

def trust(client,root):
    r=client.post("/api/developer/studio/trust",headers=AUTH,json={
        "project":str(root),"trusted":True,"confirmed":True})
    assert r.status_code==200,r.text

def patch(client,root,path="reviewable-notice.php",sha=None):
    if sha is None:
        sha=hashlib.sha256((root/path).read_bytes()).hexdigest()
    return client.post(BASE+"/patch-preview",headers=AUTH,json={
        "project":str(root),"path":path,"expected_sha256":sha})

def version_run(client,root,task="version",tool="php",**kwargs):
    found=inspect(client,root).json()
    rec=next(x for x in found["toolchains"] if x["name"]==tool)
    if rec["status"]!="installed_not_executed":
        pytest.skip("No native "+tool+" executable available in test environment.")
    return client.post(BASE+"/run",headers=AUTH,json={
        "project":str(root),"task":task,"tool":tool,
        "expected_manifest_sha256":found["composer_sha256"],
        "expected_executable":rec["executable"],
        "expected_sha256":rec["sha256"],
        "confirmed":True,"accept_unsandboxed_execution_and_write_risk":True,
        **kwargs})

def test_readonly_inspection_finds_plugin_headers_hooks_settings_and_composer(project):
    client,root=project
    originals={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    r=inspect(client,root)
    assert r.status_code==200,r.text
    value=r.json()
    assert value["composer"]["name"]=="example/reviewable-notice"
    assert "PHPUnit" in value["composer"]["frameworks"]
    assert "PHPStan" in value["composer"]["frameworks"]
    assert value["composer"]["php_requirement"]==">=8.1"
    assert value["wordpress_plugins"][0]["header"]["plugin_name"]=="Reviewable Notice"
    hooks=value["wordpress_plugins"][0]["hooks"]
    assert {x["identifier"] for x in hooks}=={
        "admin_notices","the_content","__FILE__"}
    assert {x["type"] for x in hooks}=={"add_action","add_filter","register_activation_hook"}
    assert any(x["code"]=="raw-superglobal-echo" for x in value["findings"])
    assert value["central_agent_studio"]=="developer"
    assert value["agent_deployment_handoff_required"] is True
    assert value["deployment_started"] is False
    assert value["tool_executed"] is False
    assert {p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}==originals

def test_real_wordpress_security_patch_uses_v2_checksum_save_and_preserves_hooks_and_settings(project):
    client,root=project
    old=(root/"reviewable-notice.php").read_bytes()
    resp=patch(client,root)
    assert resp.status_code==200,resp.text
    data=resp.json()
    assert data["saved"] is False
    assert data["preview_only"] is True
    assert data["preserved_hooks"]==3
    assert data["source_sha256"]==hashlib.sha256(old).hexdigest()
    assert (root/"reviewable-notice.php").read_bytes()==old
    new=data["patched_text"]
    assert "echo isset( $_GET['notice'] ) ? esc_html(" in new
    assert "sanitize_text_field( wp_unslash( $_GET['notice'] ) )" in new
    for original in ("register_activation_hook( __FILE__, 'reviewable_activate' );",
                     "update_option( 'reviewable_enabled', true );",
                     "add_action( 'admin_notices', 'reviewable_notice' );",
                     "add_filter( 'the_content', 'reviewable_content' );"):
        assert original in new
    # The existing V2 editor is the ONLY source writer. No V16 auto-change.
    assert client.post("/api/developer/studio/save-file",headers=AUTH,json={
        "project":str(root),"path":"reviewable-notice.php","text":new,
        "encoding":"utf-8","newline":"lf","expected_sha256":data["source_sha256"],
        "confirmed":True}).status_code==403
    trust(client,root)
    saved=client.post("/api/developer/studio/save-file",headers=AUTH,json={
        "project":str(root),"path":"reviewable-notice.php","text":new,
        "encoding":"utf-8","newline":"lf","expected_sha256":data["source_sha256"],
        "confirmed":True})
    assert saved.status_code==200,saved.text
    assert saved.json()["sha256"]==data["patched_sha256"]
    assert patch(client,root,sha=data["source_sha256"]).status_code==409
    assert "echo $_GET['notice'];" not in (root/"reviewable-notice.php").read_text()

def test_installed_php_syntax_and_wordpress_behavior_with_stubbed_wp_hooks(project):
    client,root=project
    exe=shutil.which("php")
    if not exe:
        pytest.skip("System php is not installed; no PHP compatibility claim.")
    proposal=patch(client,root).json()
    trust(client,root)
    data=inspect(client,root).json()
    php_tool=next(x for x in data["toolchains"] if x["name"]=="php")
    if php_tool["status"]!="installed_not_executed":
        pytest.skip("PHP executable cannot be fingerprinted safely.")
    lint=version_run(client,root,task="lint",
                     path="reviewable-notice.php",
                     expected_source_sha256=data["wordpress_plugins"][0]["sha256"])
    assert lint.status_code==200,lint.text
    assert lint.json()["status"]=="completed"
    save=client.post("/api/developer/studio/save-file",headers=AUTH,json={
        "project":str(root),"path":"reviewable-notice.php",
        "text":proposal["patched_text"],"encoding":"utf-8","newline":"lf",
        "expected_sha256":proposal["source_sha256"],"confirmed":True})
    assert save.status_code==200,save.text
    after=version_run(client,root,task="lint",path="reviewable-notice.php",
                      expected_source_sha256=save.json()["sha256"])
    assert after.status_code==200,after.text
    assert after.json()["status"]=="completed" and after.json()["exit_code"]==0
    php_stub="""
$hooks=[];$options=[];
function add_action($name,$callable){$GLOBALS['hooks'][]=$name;}
function add_filter($name,$callable){$GLOBALS['hooks'][]=$name;}
function register_activation_hook($path,$cb){$GLOBALS['activation']=$cb;}
function update_option($key,$val){$GLOBALS['options'][$key]=$val;}
function wp_unslash($s){return stripslashes($s);}
function sanitize_text_field($s){return strip_tags($s);}
function esc_html($s){return htmlspecialchars($s,ENT_QUOTES,'UTF-8');}
$_GET['notice']='<img src=x onerror=alert(1)>Check';
require 'reviewable-notice.php';
call_user_func($GLOBALS['activation']);
ob_start();reviewable_notice();$notice=ob_get_clean();
echo json_encode(['notice'=>$notice,'hooks'=>$hooks,'settings'=>$options,
 'content'=>reviewable_content('Original')]);
"""
    run=subprocess.run([exe,"-r",php_stub],cwd=root,capture_output=True,text=True,timeout=12)
    assert run.returncode==0,run.stderr
    out=json.loads(run.stdout)
    assert out["notice"]=="Check"
    assert out["hooks"]==["admin_notices","the_content"]
    assert out["settings"]=={"reviewable_enabled":True}
    assert out["content"]=="Original"

def test_stale_sha_rejected_and_only_specific_fix_pattern_supported(project):
    client,root=project
    path=root/"reviewable-notice.php"
    path.write_text(PLUGIN.replace("echo $_GET['notice'];","print($_GET['notice']);"))
    response=patch(client,root)
    assert response.status_code==422,response.text
    path.write_text(PLUGIN+"echo $_GET['notice'];\n")
    assert patch(client,root).status_code==422
    path.write_text(PLUGIN)
    assert patch(client,root,sha="f"*64).status_code==409

def test_composer_duplicate_manifest_and_restricted_paths(project,tmp_path):
    client,root=project
    (root/"composer.json").write_text('{"require":{"php":">=8"},"require":{"php":">=9"}}')
    assert inspect(client,root).status_code==422
    (root/"composer.json").write_text(json.dumps(COMPOSER))
    assert patch(client,root,path="../private.php",sha="0"*64).status_code in (403,404,422)
    (root/"--help.php").write_text(PLUGIN)
    assert patch(client,root,path="--help.php").status_code==422
    outside=tmp_path/"plugin.php"
    outside.write_text(PLUGIN)
    link=root/"link.php"
    try:
        link.symlink_to(outside)
    except (OSError,NotImplementedError):
        pass
    else:
        assert patch(client,root,path="link.php").status_code in (403,404)
        assert all(x["path"]!="link.php" for x in inspect(client,root).json()["wordpress_plugins"])

def test_task_requires_trust_fingerprint_source_sha_and_confirmations(project):
    client,root=project
    tools=inspect(client,root).json()["toolchains"]
    target=next(x for x in tools if x["name"]=="php")
    if target["status"]!="installed_not_executed":
        pytest.skip("PHP executable not available.")
    manifest=inspect(client,root).json()
    body={"project":str(root),"task":"version","tool":"php",
          "expected_manifest_sha256":manifest["composer_sha256"],
          "expected_executable":target["executable"],"expected_sha256":target["sha256"],
          "confirmed":True,"accept_unsandboxed_execution_and_write_risk":True}
    assert client.post(BASE+"/run",headers=AUTH,json=body).status_code==403
    trust(client,root)
    assert client.post(BASE+"/run",headers=AUTH,json={**body,"confirmed":False}).status_code==422
    assert client.post(BASE+"/run",headers=AUTH,json={**body,
        "accept_unsandboxed_execution_and_write_risk":False}).status_code==422
    assert client.post(BASE+"/run",headers=AUTH,json={**body,
        "expected_sha256":"0"*64}).status_code==409
    assert client.post(BASE+"/run",headers=AUTH,json={**body,
        "expected_manifest_sha256":"0"*64}).status_code==409
    success=client.post(BASE+"/run",headers=AUTH,json=body)
    assert success.status_code==200,success.text
    assert success.json()["status"]=="completed"
    assert success.json()["deployment_started"] is False
    assert success.json()["agent_deployment_approved"] is False
    (root/"composer.json").write_text((root/"composer.json").read_text()+"\n")
    assert client.post(BASE+"/run",headers=AUTH,json=body).status_code==409

def test_opt_in_project_tool_command_is_fixed_and_wordpress_readonly(project):
    client,root=project
    assert php._command(root,php.RunIn(
        project=str(root),task="lint",tool="php",path="reviewable-notice.php",
        expected_manifest_sha256="a"*64,expected_executable="/usr/bin/php",
        expected_sha256="b"*64,expected_source_sha256="c"*64,
        confirmed=True,accept_unsandboxed_execution_and_write_risk=True),"/usr/bin/php")==[
            "/usr/bin/php","-l","reviewable-notice.php"]
    with pytest.raises(Exception):
        php._command(root,php.RunIn(
            project=str(root),task="phpunit",tool="php",path="../outside.php",
            expected_manifest_sha256="a"*64,expected_executable="/usr/bin/php",
            expected_sha256="b"*64,confirmed=True,
            accept_unsandboxed_execution_and_write_risk=True),"/usr/bin/php")
    assert not (root/"vendor").exists()

def test_hosted_routes_denied_and_auth_precedes_any_source_access(project):
    client,root=project
    for name in ("inspect",):
        assert path_allowed("GET",BASE+"/"+name) is False
    for name in ("patch-preview","run"):
        assert path_allowed("POST",BASE+"/"+name) is False
    assert client.get(BASE+"/inspect",params={"project":str(root)}).status_code==403
    assert client.post(BASE+"/patch-preview",json={
        "project":str(root),"path":"reviewable-notice.php",
        "expected_sha256":hashlib.sha256(PLUGIN.encode()).hexdigest()}).status_code==403
    assert client.post(BASE+"/run",json={
        "project":str(root),"task":"version","tool":"php",
        "expected_manifest_sha256":"a"*64,"expected_executable":"/usr/bin/php",
        "expected_sha256":"b"*64,"confirmed":True,
        "accept_unsandboxed_execution_and_write_risk":True}).status_code==403
