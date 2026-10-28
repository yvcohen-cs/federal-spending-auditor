"""Bounded POSIX pilot journal, exclusive append-only files and cooperative lock."""
import fcntl
import os
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, _directory, canonical, digest, parts, strict_json
from .review_packet_io import atomic_create, new_directory


class PilotStore:
    def __init__(self, path, plan, resume=False):
        self.path, self.plan, self.resume = Path(path).absolute(), plan, resume
        self.fd = -1

    def __enter__(self):
        if not self.resume:
            for ancestor in (self.path.parent,)+tuple(self.path.parent.parents):
                with EvidenceRoot(ancestor) as root:
                    for marker in ("pilot-plan.json", "research-plan.json"):
                        try:
                            os.stat(marker, dir_fd=root.fd, follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        raise EvidenceError("pilot_inside_managed_run")
            new_directory(self.path)
        self.fd = _directory(self.path)
        try:
            fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self.resume:
                if digest(self.json("pilot-plan.json")) != digest(self.plan):
                    raise EvidenceError("incompatible_pilot_plan")
            else:
                self.write("pilot-plan.json", self.plan)
            self.inventory()
            return self
        except BaseException:
            os.close(self.fd)
            self.fd = -1
            raise

    def __exit__(self,*args):
        if self.fd != -1:
            os.close(self.fd)
            self.fd = -1

    def reader(self):
        probe = _directory(self.path)
        try:
            a,b=os.fstat(probe),os.fstat(self.fd)
            if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino):
                raise EvidenceError("pilot_root_changed")
        finally:
            os.close(probe)
        return EvidenceRoot(self.path,max_bytes=32*1024*1024,max_total_bytes=self.plan["config"]["max_run_bytes"],max_files=20000)

    def inventory(self):
        with self.reader() as root:
            paths=root.discover()
            # Read every file to enforce size/type/hardlink and aggregate bounds.
            return {p:root.read(p).byte_sha256 for p in paths}

    def read(self,name):
        with self.reader() as root:
            return root.read(name).data

    def json(self,name):
        return strict_json(self.read(name))

    def write(self,name,value):
        self.write_bytes(name,(canonical(value)+"\n").encode())

    def write_bytes(self,name,raw):
        parts(name)
        with self.reader() as root:
            size=sum(len(root.read(p).data) for p in root.discover())
        if len(raw)>32*1024*1024 or size+len(raw)>self.plan["config"]["max_run_bytes"]:
            raise EvidenceError("pilot_size_limit")
        fd=_directory((self.path/name).parent)
        try:
            atomic_create(fd,Path(name).name,raw)
        finally:
            os.close(fd)
        if self.read(name)!=raw:
            raise EvidenceError("pilot_output_changed")

    def mkdir(self,name):
        parts(name)
        fd=os.dup(self.fd)
        try:
            for part in parts(name):
                try:
                    os.mkdir(part,0o700,dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd)
                fd=child
        finally:
            os.close(fd)
