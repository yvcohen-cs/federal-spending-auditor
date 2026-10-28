"""C7 POSIX append-only stage commits. No overwrite/recovery by inference."""
from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, _directory, canonical, digest, parts, strict_json
from .research_models import ResearchArtifact, ResearchStage, STAGES, StageState
from .review_packet_io import atomic_create, new_directory


class ResearchStore:
    def __init__(self,path,plan,*,resume=False):
        self.path,self.plan,self.resume = Path(path).absolute(),plan,resume
        self.fd = -1

    def __enter__(self):
        if not self.resume:
            for ancestor in (self.path.parent,) + tuple(self.path.parent.parents):
                probe = _directory(ancestor)
                try:
                    try:
                        os.stat("research-plan.json",dir_fd=probe,follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    raise EvidenceError("research_run_inside_existing_run")
                finally:
                    os.close(probe)
            new_directory(self.path)
        self.fd = _directory(self.path)
        try:
            fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self.resume:
                if digest(self.json("research-plan.json")) != digest(self.plan):
                    raise EvidenceError("incompatible_research_plan")
            else:
                self.write("research-plan.json",self.plan)
            self.audit()
            return self
        except BaseException:
            os.close(self.fd); self.fd = -1
            raise

    def __exit__(self,*args):
        if self.fd != -1:
            os.close(self.fd); self.fd = -1

    def root_check(self):
        probe = _directory(self.path)
        try:
            a,b = os.fstat(self.fd),os.fstat(probe)
            if (a.st_dev,a.st_ino) != (b.st_dev,b.st_ino):
                raise EvidenceError("research_root_changed")
        finally:
            os.close(probe)

    def reader(self):
        return EvidenceRoot(self.path,max_bytes=32*1024*1024,max_total_bytes=self.plan["config"]["max_run_bytes"],max_files=12000)

    def read(self,name):
        self.root_check()
        with self.reader() as root:
            return root.read(name).data

    def json(self,name):
        return strict_json(self.read(name))

    def mkdir(self,relative):
        self.root_check()
        fd = os.dup(self.fd)
        try:
            for segment in parts(relative):
                try:
                    os.mkdir(segment,0o700,dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
                child = os.open(segment,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd); fd = child
        finally:
            os.close(fd)
        self.root_check()

    def write(self,name,value):
        self.write_bytes(name,(canonical(value)+"\n").encode())

    def write_bytes(self,name,raw):
        segments = parts(name)
        self.root_check()
        if self.used_bytes()+len(raw) > self.plan["config"]["max_run_bytes"]:
            raise EvidenceError("research_run_size_limit")
        parent = _directory(self.path.joinpath(*segments[:-1]))
        try:
            atomic_create(parent,segments[-1],raw)
        finally:
            os.close(parent)
        if self.read(name) != raw:
            raise EvidenceError("research_output_changed")

    def used_bytes(self):
        total = 0
        with self.reader() as root:
            for name in root.discover():
                fd = root._open(name)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
                        raise EvidenceError("unsafe_research_file_type")
                    total += info.st_size
                finally:
                    os.close(fd)
        return total

    def audit(self):
        self.root_check()
        with self.reader() as root:
            paths = root.discover()
            committed = tuple(s for s in STAGES if f"stage-{s}.json" in paths)
            if committed != STAGES[:len(committed)]:
                raise EvidenceError("invalid_research_stage_commit_order")
            for path in paths:
                if not (path == "research-plan.json" or re.fullmatch(r"stage-(?:acquire|verify|identity|finance|packets|summary)\.json",path)
                        or re.fullmatch(r"research-run-[0-9]{6}\.json",path)
                        or re.fullmatch(r"failures/(?:acquire|verify|identity|finance|packets|summary)-[0-9]{3}\.json",path)
                        or re.fullmatch(r"artifacts/(?:acquire|verify|identity|finance|packets|summary)/attempt-[0-9]{3}/.+",path)
                        or any(s["managed"] and path.startswith(s["path"]+"/") for s in self.plan["sources"])):
                    raise EvidenceError("unexpected_research_artifact")
                snap = root.read(path)
                if path.startswith("failures/"):
                    from .research_models import ResearchDiagnostic
                    ResearchDiagnostic.from_dict(strict_json(snap.data))
                if path.startswith("research-run-"):
                    from .research_models import ResearchRun
                    doc = strict_json(snap.data)
                    previous = ResearchRun.from_dict(doc["run"])
                    expected = {"run":previous.to_dict(),"substantive_sha256":previous.substantive_sha256,
                        "technical_success":previous.technical_success,"evidentiary_complete":previous.evidentiary_complete,"exit_code":previous.exit_code}
                    if digest(doc)!=digest(expected):
                        raise EvidenceError("research_run_manifest_conflict")
            if digest(strict_json(root.read("research-plan.json",recheck=True).data)) != digest(self.plan):
                raise EvidenceError("research_plan_changed")
            if root.discover() != paths:
                raise EvidenceError("research_inventory_changed")
        return paths

    def receipt(self,stage,expected_input):
        name = f"stage-{stage}.json"
        if name not in self.audit():
            return None
        doc = self.json(name)
        if (set(doc) != {"schema_type","schema_version","plan_sha256","result"}
                or doc["schema_type"] != "ResearchStageCommit" or type(doc["schema_version"]) is not int or doc["schema_version"] != 1
                or doc["plan_sha256"] != digest(self.plan)):
            raise EvidenceError("invalid_research_stage_commit")
        result = ResearchStage.from_dict(doc["result"])
        if result.stage != stage or result.state is not StageState.COMPLETED or result.input_sha256 != expected_input:
            raise EvidenceError("stale_research_stage_commit")
        prefixes = set()
        for a in result.artifacts:
            match = re.fullmatch(r"artifacts/"+stage+r"/attempt-([0-9]{3})/(.+)",a.storage_path)
            if match is None or int(match[1]) >= self.plan["config"]["max_attempts"] or a.name != match[2]:
                raise EvidenceError("invalid_research_artifact_reference")
            prefixes.add(a.storage_path[:a.storage_path.index("/",len("artifacts/"+stage+"/"))])
        if len(prefixes) != 1:
            raise EvidenceError("mixed_research_stage_attempts")
        prefix = next(iter(prefixes))
        with self.reader() as root:
            paths = tuple(p for p in root.discover() if p.startswith(prefix+"/"))
            if set(paths) != {a.storage_path for a in result.artifacts}:
                raise EvidenceError("incomplete_research_stage_outputs")
            for a in result.artifacts:
                snap = root.read(a.storage_path)
                if snap.byte_sha256 != a.sha256 or len(snap.data) != a.byte_count:
                    raise EvidenceError("research_stage_output_hash_conflict")
        return result

    def attempt(self,stage,*,retry=False):
        relative = "artifacts/"+stage
        base = self.path/relative
        names = []
        if base.exists():
            fd = _directory(base)
            try:
                names = sorted(os.listdir(fd))
            finally:
                os.close(fd)
        if names != [f"attempt-{i:03d}" for i in range(len(names))]:
            raise EvidenceError("invalid_research_attempt_inventory")
        if names and not retry:
            raise EvidenceError("explicit_retry_required_for_uncommitted_stage")
        if len(names) >= self.plan["config"]["max_attempts"]:
            raise EvidenceError("research_attempt_limit")
        self.mkdir(relative)
        attempt = f"{relative}/attempt-{len(names):03d}"
        self.mkdir(attempt)
        return attempt,len(names)

    def commit(self,stage,input_sha,attempt,*,validate=None):
        with self.reader() as root:
            paths = tuple(p for p in root.discover() if p.startswith(attempt+"/"))
            artifacts = tuple(ResearchArtifact(name=p[len(attempt)+1:],sha256=(snap:=root.read(p)).byte_sha256,
                byte_count=len(snap.data),storage_path=p) for p in paths)
        result = ResearchStage(stage=stage,state=StageState.COMPLETED,input_sha256=input_sha,artifacts=artifacts)
        if validate:
            validate(result)
        self.write(f"stage-{stage}.json",{"schema_type":"ResearchStageCommit","schema_version":1,"plan_sha256":digest(self.plan),"result":result.to_dict()})
        return self.receipt(stage,input_sha)
