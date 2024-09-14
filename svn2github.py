#!/usr/bin/env python3

# NOTE please read TODO.md

# TODO store github login in a private file
github_username = "your_github_username" # TODO
github_token = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" # TODO

__program__ = "svn2github"
__version__ = "0.0.1"

import subprocess
import re
import collections
import os
import tempfile
import shutil
import sys
import argparse
import inspect
import time
import urllib
import urllib.parse
import json
import glob
import datetime
import types
import logging
import io

# short loglevel names
#logging._levelToName = { 0: '?', 10: 'd', 20: 'i', 30: 'w', 40: 'e', 50: 'c' }
# ansi colors
#logging._levelToName = { 0: '?', 10: 'DEBG \x1b[45m \x1b[0m', 20: 'INFO  ', 30: 'WARN \x1b[43m \x1b[0m', 40: 'ERRO \x1b[41m \x1b[0m', 50: 'CRIT \x1b[41m \x1b[0m' }
# unicode color bullets  🟣 🔴 🟤 🟠 🟡 🟢 🔵
#logging._levelToName = { 0: '?', 10: 'DEBG 🔵', 20: 'INFO   ', 30: 'WARN 🟠', 40: 'ERRO 🔴', 50: 'CRIT 🔴' }
logging._levelToName = { 0: '?', 10: 'DEBG   ', 20: 'INFO 🟢', 30: 'WARN 🟠', 40: 'ERRO 🔴', 50: 'CRIT 🔴' }

#GitSvnInfo = collections.namedtuple('GitSvnInfo', 'svn_url svn_revision svn_uuid')

log_level = logging.DEBUG # debug by default. make it easier for users to report bugs

is_debug = os.environ.get("DEBUG", False) or ("--debug" in sys.argv)
#is_debug = True
if is_debug:
    sys.argv = list(filter(lambda v: v != "--debug", sys.argv))

def init_log(
        level=logging.DEBUG, # debug by default. make it easier for users to report bugs
    ):

	log = logging.getLogger(__program__)
	log.setLevel(level)

	log._stderr_handler = logging.StreamHandler() # default stream: sys.stderr
	log.addHandler(log._stderr_handler)

	log_formatter = logging.Formatter(
		# message format:
		'%(asctime)s %(lineno)3d %(levelname)s %(message)s',
		# time format:
		#"%Y-%m-%d %H:%M:%S",
	)
	[h.setFormatter(log_formatter) for h in log.handlers]

	# make the logger methods behave like info()
    # so we can use, for example, info("some.var:", some.var)
	def wrap_log_method(log_method):
		def new_log(*args, **kwargs):
			# https://stackoverflow.com/a/39823534/10440128
			f = io.StringIO()
			print(*args, file=f, end="", **kwargs)
			string = f.getvalue()
			f.close()
			log_method(string, stacklevel=2) # stacklevel: fix lineno https://stackoverflow.com/a/55998744/10440128
		return new_log
	log.debug = wrap_log_method(log.debug)
	log.info = wrap_log_method(log.info)
	log.warning = wrap_log_method(log.warning)
	log.error = wrap_log_method(log.error)

	return log

log = init_log()

debug = log.debug
info = log.info
warn = log.warning
error = log.error
critical = log.critical

info(f"{__program__} version {__version__}")
debug("debug is enabled")

if False:
    # test
    debug('debug message')
    info('info message')
    warn('warning message')
    error('error message')
    critical('critical message')
    sys.exit() # debug



default_env = {}
default_env.update(os.environ)
default_env['LANG'] = 'C'
default_env['LC_ALL'] = 'C' # fix date format for 'svn log'


run_kwargs_default = {
    'check': True,
    'stdin': subprocess.DEVNULL,
    'stdout': subprocess.PIPE,
    'env': default_env,
    'encoding': 'utf8',
}


popen_kwargs_default = {
    'stdin': subprocess.DEVNULL,
    'stdout': subprocess.PIPE,
    'env': default_env,
}


def popen(*args, **kwargs):
    if type(args[0]) == str:
        args = list(args)
        args[0] = re.split(r"\s+", args[0])
        args = tuple(args)
    if 'cwd' in kwargs:
        debug("run: ( cd " + kwargs['cwd'] + " && " + " ".join(args[0]) + " )")
    else:
        debug("run: " + " ".join(args[0]))
    kwargs = {**popen_kwargs_default, **kwargs}
    return subprocess.Popen(*args, **kwargs)


def run(*args, **kwargs):
    debug("run: args =", args)
    debug("run: kwargs =", kwargs)
    if type(args[0]) == str:
        args = list(args)
        args[0] = re.split(r"\s+", args[0])
        args = tuple(args)
    if 'cwd' in kwargs:
        debug("run: ( cd " + kwargs['cwd'] + " && " + " ".join(args[0]) + " )")
    else:
        debug("run: " + " ".join(args[0]))
    if 'env' in kwargs:
        e = default_env.copy()
        e.update(kwargs['env'])
        kwargs['env'] = e
    kwargs = {**run_kwargs_default, **kwargs}
    result = subprocess.run(*args, **kwargs)
    if is_debug:
        info("run: stdout:")
        info(result.stdout)
        info(":stdout")
        if result.stderr != None:
            info("run: stderr:")
            info(result.stderr)
            info(":stderr")
    return result


def get_last_revision_from_svn(svn_url):
    args = ["svn", "info", svn_url, "--no-newline", "--show-item", "revision"]
    result = run(args)
    rev = int (result.stdout.decode().strip())
    if rev:
        return rev

    return Exception("svn info {} output did not specify the current revision".format(svn_url))


def run_git_cmd(args, git_dir):
    args = ["git"] + args
    return run(args, cwd=git_dir)


def is_repo_empty(git_dir):
    args = ["ls", ".git/refs/heads"]
    result = run(args, cwd=git_dir)
    return len(result.stdout) == 0




def svnsync_init(svn_url, svnrepo_dir):
    os.makedirs(os.path.dirname(svnrepo_dir), exist_ok=True)
    # --compatible-version=1.9.0
    # to make the svn repo compatible with sourceforge.net
    # sourceforge.net has svn version 1.9.5 (svnfs version 1.9.0)
    # latest svn version 1.14.0 (svnfs version 1.10.0)
    run(["svnadmin", "create", "--compatible-version=1.9.0", os.path.basename(svnrepo_dir)], cwd=os.path.dirname(svnrepo_dir))
    #run(["svnsync", "initialize", "file://"+svnrepo_dir, config['svn_url']])
    #run(["svnsync", "initialize", "file://"+svnrepo_dir, git_svn_info.svn_url]) # FIXME
    run(["svnsync", "init", "file://"+svnrepo_dir, svn_url]) # FIXME
    # svnsync initialize: --source-username user --source-password pass


def svnsync_sync(svnrepo_dir):
    # TODO make svn checkout faster: --no-auth-cache --non-interactive ... no effect
    #   maybe try golang impl of svn https://github.com/Masterminds/vcs
    # TODO support --source-username and --source-password
    #args = ["svnsync", "synchronize", "file://"+svnrepo_dir]
    # svnrepo_dir must be absolute path
    #svnrepo_dir = os.path.abspath(svnrepo_dir)

    # fix: svnsync: E165006: Repository has not been enabled to accept revision propchanges
    hookfile = svnrepo_dir+"/hooks/pre-revprop-change"
    with open(hookfile, "w") as f:
        f.write("\n".join(["#!/bin/sh", "exit 0"]))
    os.chmod(hookfile, 0o755)

    args = ["svnsync", "sync", "file://"+svnrepo_dir]
    info("run: "+" ".join(args))
    cmd = popen(args, universal_newlines=True)
    pattern = re.compile("^Committed revision ([0-9]+)\.")
    while True:
        line = cmd.stdout.readline()
        #info("line = " + repr(line))
        if not line:
            break
        m = pattern.match(line)
        #info("m = " + repr(m))
        if m:
            yield int(m.group(1))


def git_svn_rebase(git_dir):
    run_git_cmd(["svn", "rebase"], git_dir)


def git_svn_fetch(git_dir):
    args = ["git", "svn", "fetch"]
    info("run: ( cd "+git_dir+" && "+" ".join(args)+" )")
    cmd = popen(args, cwd=git_dir, universal_newlines=True)

    pattern = re.compile("^r([0-9]+) = [0-9a-f]{40}")

    while True:
        line = cmd.stdout.readline()
        #info("git_svn_fetch line = " + repr(line))
        if not line:
            break
        m = pattern.match(line)
        if m:
            yield int(m.group(1))


def git_clone(git_src, git_dir):
    os.makedirs(git_dir, exist_ok=False)
    run_git_cmd(["clone", git_src, "."], git_dir)


def git_push(git_dir):
    run_git_cmd(["push", "origin", "master"], git_dir)



def format_dt(seconds):
    # round to remove microseconds (useless when dt is 1 hour)
    return str(datetime.timedelta(seconds = round(seconds)))


svn2github_url = "https://github.com/milahu/svn2github"



readme_md_template = """\
# {git_repo_name}

this git repo was generated with [svn2github.py]({svn2github_url})

## config

### svn url

```
{svn_url}
```

### svn-all-fast-export

rules file for [svn-all-fast-export](https://github.com/svn-all-fast-export/svn2git)

`{git_repo_name}.rules`

```
{svn2git_rules}
```
"""

def write_md_file(md_file, **kwargs):
    md = readme_md_template.format(**kwargs)
    with open(md_file, "w") as f:
        f.write(md)



def sync_github_mirror(args):

    debug("args", args)

    args.workdir = os.path.abspath(args.workdir)

    workdir = args.workdir
    assert os.path.exists(workdir)

    #git_dir = os.path.join(workdir, "git")
    config_file = os.path.join(workdir, "svn2github.json")

    info("workdir = " + workdir)
    #info("git_dir = " + git_dir)
    info("config_file = " + config_file)

    #sys.exit() # debug

    config = None
    svn_url = None

    if os.path.exists(config_file):

        info(f"reading config file {config_file}")

        with open(config_file, "r") as fd:

            # dict to namespace
            # https://stackoverflow.com/questions/50490856
            # https://stackoverflow.com/questions/66208077

            def dict_to_sns(d):
                return types.SimpleNamespace(**d)

            try:
                config = json.load(fd, object_hook=dict_to_sns)
            except Exception as e:
                info(f"failed to load config file {config_file}")
                raise e

        svn_inputs = list(filter(lambda repo: hasattr(repo, "original") and repo.original == True, config.repos))
        if len(svn_inputs) != 1:
            raise Exception("""config error: the config.repos array must have exactly one { "original": true } entry""")
        svn_url = svn_inputs[0].remotes[0].url
        debug("svn_url =", svn_url)

        git_outputs = list(filter(lambda repo: getattr(repo, "enabled", True) == True and repo.type == "git" and hasattr(repo.branches, "main") and getattr(repo, "write", False) == True, config.repos))
        if len(git_outputs) != 1:
            raise Exception("""config error: the config.outputs array must have exactly one { "type": "git", "write": true, "branches": { "main": "..." } } entry""")
            # TODO implement multiple output repos
        git_url = git_outputs[0].remotes[0].url
        debug("git_url =", git_url)

        svn_outputs = list(filter(lambda repo: getattr(repo, "enabled", True) == True and repo.type == "svn" and getattr(repo, "original", False) == False and getattr(repo, "write", False) == True, config.repos))
        if len(git_outputs) != 1:
            raise Exception("""config error: the config.outputs array must have exactly one { "type": "svn", "write": true } entry""")
            # TODO implement multiple output repos
        svn_output_url = svn_outputs[0].remotes[0].url
        debug("svn_output_url =", svn_output_url)
        #debug("svnrepo_git_url =", svnrepo_git_url) # TODO remove

        debug("reading config done:", config)

    else:

        debug(f"no config file {config_file}")
        raise Exception("""no config file. not implemented. please add config file {config_file}""")
        #if not svn_url:
        #    raise "you must set svn_url on the first run"
        #config['svn_url'] = svn_url
        #config_changed = True

    #if config_changed:
    if False:
 
        # only write when not exists
        info(f"writing config file {config_file}")
        fd = open(config_file, "w")
        json.dump(config, fd, indent=2)
        fd.close()

    if False: # keep indent

        cached = os.path.exists(git_dir+"/.git")
        #info("cached = "+repr(cached))
        #info("svn_url = "+repr(svn_url))
        #if cached and not svn_url:
        if cached:
            info(f"Using Git repository {git_dir}")
        else:
            info(f"Cloning Git repository {git_dir} from {git_url}")
            git_clone(git_url, git_dir) # TODO verify: must be full clone

        #os.mkdir(svnrepo_dir)

    if True: # keep indent

        if False:
            if svn_url:
                git_svn_info = GitSvnInfo(svn_url=svn_url, svn_revision=0, svn_uuid=None)
                if not is_repo_empty(git_dir):
                    #raise Exception("Specifed svn_url, but the destination repo is not empty")
                    git_svn_info_old = get_svn_info_from_git(git_dir)
                    if git_svn_info_old.svn_url != git_svn_info.svn_url:
                        info("error: mismatch in svn url")
                        info("local: ", repr(git_svn_info_old.svn_url))
                        info("remote:", repr(git_svn_info.svn_url))
                        raise Exception("mismatch in svn url")
            else:
                git_svn_info = get_svn_info_from_git(git_dir)

        if False:
            svn_host = urllib.parse.urlparse(config['svn_url']).hostname
            svn_path = urllib.parse.urlparse(config['svn_url']).path
            svn_path = re.sub(r"^/*(.*?)/*$", r"\1", svn_path) # remove leading and trailing slashes

        svn_host = urllib.parse.urlparse(svn_url).hostname
        svn_path = urllib.parse.urlparse(svn_url).path
        svn_path = re.sub(r"^/*(.*?)/*$", r"\1", svn_path) # remove leading and trailing slashes

        #svnrepo_dir = os.path.join(workdir, "svnrepo", svn_host, svn_path)
        svnrepo_dir = os.path.join(workdir, "svnrepo")
        info("svnrepo_dir = " + svnrepo_dir)

        #svn_working_copy_dir = os.path.join(workdir, "svn-working-copy", svn_host, svn_path)
        #info("svn_working_copy_dir = " + svn_working_copy_dir)

        need_svn_fetch = True

        debug("svn_url =", repr(svn_url))
        debug(f"run: svn info {svn_url}")
        svn_info_upstream = run(["svn", "info", svn_url]).stdout.strip()
        info("svn_info_upstream:\n" + svn_info_upstream)
        svn_info_upstream = dict(line.split(': ') for line in svn_info_upstream.split("\n"))

        info("Checking for SVN updates")
        upstream_revs = int(svn_info_upstream['Revision'])
        mirror_revs = None # make global. set later
        #upstream_revs = get_last_revision_from_svn(config['svn_url'])
        info(f"Last revision of upstream: {upstream_revs}")

        if os.path.exists(svnrepo_dir):
            info(f"Found local SVN repo {svnrepo_dir}")
            svn_info = run(["svnadmin", "info", svnrepo_dir]).stdout.strip()
            info("svn_info:\n" + svn_info)
            svn_info = dict(line.split(': ') for line in svn_info.split("\n"))
            # TODO rename
            #   svn_info is "svn repo info"
            #   svn_info_upstream is "svn xxx info"
            # FIXME why mismatch?
            # https://svn.haxx.se/users/archive-2007-01/0638.shtml
            # https://stackoverflow.com/questions/24635694/svn-change-uuid
            if svn_info['UUID'] != svn_info_upstream['Repository UUID']:
                # uuid's are only equal when syncing with rsync
                # when syncing with svnsync, the uuid's will be different
                info(
                    f"mismatch in UUID:\n"
                    f"  {svn_info_upstream['Repository UUID']} upstream {svn_url}\n"
                    f"  {svn_info['UUID']} local file://{svnrepo_dir}"
                )
                info("fixing the local UUID to match the upstream UUID")
                run(["svnadmin", "setuuid", svnrepo_dir, svn_info_upstream['Repository UUID']])
                # uuid is stored in the file db/uuid
            svn_uuid = svn_info['UUID'] # TODO add svn_uuid to commit messages
            mirror_revs = int(svn_info['Revisions'])
            info(f"Last revision of mirror: {mirror_revs}")

            if upstream_revs == mirror_revs:
                info(f"Local SVN is up to date -> skip update")
                need_svn_fetch = False

        if need_svn_fetch:
            info(f"Updating local SVN repo {svnrepo_dir}")

            info("Trying rsync protocol for fast download")
            # rsync is about 50x faster than svn protocol
            # rsync protocol works for these hosts:
            #   svn.code.sf.net
            #     a: svn://svn.code.sf.net /p/qmmp-dev/code
            #     b:       svn.code.sf.net::p/qmmp-dev/code

            rsync_url = svn_host+"::"+svn_path

            try:
                # TODO show speed in rev/sec
                t1 = time.time()
                args = [
                    "rsync",
                    #"--verbose",
                    "--recursive",
                    "--human-readable",
                    rsync_url,
                    os.path.dirname(svnrepo_dir)
                ]
                run(args, stdout=None)
                dt = time.time() - t1
                info(f"Done fetching in {dt:.2f} seconds")

            # TODO use svnrdump -> much faster than svnsync
            # svnrdump dump --quiet --incremental --revision 0000:0999 --file svn-dump.0 svn://svn.appwork.org/utils
            # svnrdump dump --quiet --incremental --revision 1000:1999 --file svn-dump.1 svn://svn.appwork.org/utils
            # svnrdump dump --quiet --incremental --revision 2000:2999 --file svn-dump.2 svn://svn.appwork.org/utils
            # ...
            # svnadmin create svnrepo/
            # svnadmin load --quiet --file svn-dump.0 svnrepo/
            # svnadmin load --quiet --file svn-dump.1 svnrepo/
            # svnadmin load --quiet --file svn-dump.2 svnrepo/
            # ...
            # svn info svn://svn.appwork.org/utils | grep UUID
            # svnadmin info svnrepo/ | grep UUID
            #### svnadmin setuuid svnrepo/ 21714237-3853-44ef-a1f0-ef8f03a7d1fe # not needed

            except Exception as e:
                info("Failed to use rsync protocol. Error: " + str(e))
                info("Using SVN protocol")

                #sys.exit() # debug

                cached = os.path.exists(svnrepo_dir)
                #info("cached = "+repr(cached))
                #info("svn_url = "+repr(svn_url))
                #if cached and not svn_url:
                if not cached:
                    info(f"Creating local SVN repo in {svnrepo_dir}")
                    svnsync_init(svn_url, svnrepo_dir)

                info(f"Fetching {upstream_revs} revisions ...")
                info("Note: This is slow, cos the SVN protocol is slow")
                info("t1 = " + time.strftime("%F %T %z"))
                # https://www.mediawiki.org/wiki/Making_Subversion_faster
                # https://svn.haxx.se/dev/archive-2007-11/0223.shtml
                debug("starting svnsync_sync loop")
                print("svnsync_sync ", end="")
                #sys.stdout.flush()
                t1 = time.time()
                now_last_10 = time.time()
                done_revs = 0
                eta = "?"
                for rev in svnsync_sync(svnrepo_dir):
                    #info("Fetching from SVN, revision {}/{}".format(rev, upstream_revs))
                    # more compact: print 10 revisions per line
                    if rev % 10 == 0: # first rev is 1
                        percent = round(rev/upstream_revs*100)
                        now = time.time()
                        dt = now - t1
                        dt_10 = now - now_last_10
                        speed = 10 / dt_10
                        now_last_10 = now
                        eta = (upstream_revs - rev) / speed
                        print(f"{rev} of {upstream_revs} = {percent}% @ {speed:.2f} rev/sec | took {dt:.2f} sec | eta {format_dt(eta)}")
                        print("svnsync_sync ", end="")
                    else:
                        print("{} ".format(rev), end="")
                        # print every revision, so we can trace errors
                        # syncing revisions can fail, so we need to skip revisions
                    done_revs += 1
                print() # newline
                debug("done svnsync_sync loop")
                dt = time.time() - t1
                info("t2 = " + time.strftime("%F %T %z"))
                speed = done_revs / dt
                info(f"Fetched {done_revs} revisions in {dt:.2f} seconds = {speed:.2f} rev/sec")

        # sync done. get actual svn_info
        svn_info = run(["svnadmin", "info", svnrepo_dir]).stdout.strip()
        info("svn_info:\n" + svn_info)
        svn_info = dict(line.split(': ') for line in svn_info.split("\n"))
        mirror_revs = int(svn_info['Revisions'])

        if upstream_revs != mirror_revs:
            raise Exception(f"SVN sync failed.\n{upstream_revs} upstream revs (expected)\n{mirror_revs} local revs (actual)")

        # TODO handle errors, maybe try other protocols, finally fallback to slow svn protocol
        # rsync will create svnrepo_dir
        #else:
        #    info("using the slow SVN protocol. maybe the server "+asdf+" supports rsync protocol?")

        # TODO store SVN rev's as git tags
        # git tag -a r12455 5961e89211942f028e2e57a1fce18074aef90786 -m ""

        need_svn_to_git = True
        mirror_coms = 0

        #if os.path.exists(git_dir):
        if False:
            info(f"Found local Git repo {git_dir}")
            try:
                #mirror_coms = int(run("git rev-list --count HEAD", cwd=git_dir, stderr=subprocess.DEVNULL).stdout.strip())
                mirror_coms = int(run("git rev-list --count master", cwd=git_dir, stderr=subprocess.DEVNULL).stdout.strip())
                #mirror_coms = int(run("git rev-list --count main", cwd=git_dir, stderr=subprocess.DEVNULL).stdout.strip())
                # TODO auto-detect name of "main" branch
            except subprocess.CalledProcessError:
                info("Found no commits")
                pass
            info(f"Last revision of local: {mirror_coms}")
            info(f"Last revision of upstream: {mirror_revs}")
            if mirror_revs == mirror_coms:
                info(f"Local Git is up to date -> skip convert")
                need_svn_to_git = False



        # convert svn repo to git repos
        # https://github.com/svn-all-fast-export/svn2git
        # note: no "file://" prefix for svnrepo_dir
        # always run svn-all-fast-export, as it's fast

        identity_domain = svn_host
        if identity_domain.startswith("svn."):
            identity_domain = identity_domain[4:] # remove "svn." prefix
        info(f"guessed identity_domain {identity_domain} from svn_host {svn_host}")

        git_repos_dir = os.path.join(workdir, "git-repos")
        os.makedirs(git_repos_dir, exist_ok=True)

        #svn2git_rules_file_list = glob.glob(git_repos_dir + "/*.rules")
        svn2git_rules_file_list = glob.glob(workdir + "/*.rules")

        for svn2git_rules_file in svn2git_rules_file_list:
            info(f"calling svn-all-fast-export with rules file {svn2git_rules_file}")
            #svn2git_rules_file = os.path.basename(svn2git_rules_file)
            run(
                [
                    "svn-all-fast-export",
                ] + (
                    ["--debug-rules"] if is_debug else []
                ) + [
                    "--rules", "../" + os.path.basename(svn2git_rules_file), # basename -> pretty output
                    "--stats",
                    "--identity-domain", identity_domain,
                    os.path.abspath(svnrepo_dir)
                ],
                cwd=git_repos_dir,
            )

            # convention: rules filename == f"{git_repo_name}.rules"
            git_repo_name = os.path.basename(svn2git_rules_file)[0:-6] # remove ".rules" suffix
            git_repo_dir = os.path.join(git_repos_dir, git_repo_name)
            debug(f"git_repo_dir = {git_repo_dir}")

            info("turning 'bare' git repo into normal git repo")
            run("git config core.bare false", cwd=git_repo_dir)

            info("getting git commits")
            if is_debug:
                debug("git branches:")
                run("git branch", cwd=git_repo_dir) # debug: list branches

            # fatal: this operation must be run in a work tree
            # -> git_repo_dir is a "bare repo"
            # -> fix .git/config
            # a: bare = true
            # b: bare = false
            try:
                git_co = run(["git", "checkout", "main"], cwd=git_repo_dir)
            except Exception as e:
                # error: The following untracked working tree files would be removed by checkout:
                warn(f"ignoring error: {e}")
                warn(f"ignoring git error: {git_co.stderr}")

                run(["git", "reset", "--hard"], cwd=git_repo_dir)
                run(["git", "checkout", "main"], cwd=git_repo_dir)

            git_log = run(
                ["git", "log", "--pretty=format:%H%x00%aI%x00%an%x00%ae%x00%D"], # %H %aI %an %ae %D = hash time user email tags
                cwd=git_repo_dir
            )
            git_commit_list = []
            GitCommit = collections.namedtuple('GitCommit', 'hash time user email tags')
            for line in git_log.stdout.splitlines():
                commit_data = line.split("\x00")
                debug(f"commit_data = {commit_data}")
                [hash, commit_time, user, email, tags] = commit_data
                tags = set(map(lambda s: s[5:], filter(lambda s: s.startswith("tag: "), tags.split(", "))))
                git_commit = GitCommit(hash=hash, time=commit_time, user=user, email=email, tags=tags)
                git_commit_list.append(git_commit)
            git_commit_list.reverse() # "git log" lists commits from new to old
            info(f"found {len(git_commit_list)} git commits")
            debug(f"first git commit: {git_commit_list[0]}")
            debug(f"last  git commit: {git_commit_list[-1]}")

            info("adding git tags, to map from svn revision to git commit")
            # example: f"{git_repos_dir}/log-MyJDownloaderClient_.git"
            svn2git_log_file = os.path.join(git_repos_dir, f"log-{git_repo_name}_.git")
            debug(f"svn2git_log_file = {svn2git_log_file}")

            with open(svn2git_log_file, "r") as fd:
                is_first = True
                last_svn_rev = None
                for line in fd.readlines():
                    # parse lines: "progress SVN r20429 branch main = :32"
                    # stop at line: "fast-import statistics:"
                    m = re.match(r"progress SVN (r[0-9]+) branch main = :([0-9]+)\n", line)
                    if not m:
                        debug(f"last svn rev: {last_svn_rev}")
                        debug(f"stop parsing svn2git log at line {repr(line)}")
                        break
                    svn_rev = m.group(1)
                    if is_first:
                        debug(f"first svn rev: {svn_rev}")
                        is_first = False
                    git_commit_number = int(m.group(2)) # numbers are 1-based
                    git_commit = git_commit_list[git_commit_number - 1]
                    if False:
                        # debug: remove old tags
                        if svn_rev in git_commit.tags:
                            run(["git", "tag", "-d", svn_rev], cwd=git_repo_dir)
                            git_commit.tags.remove(svn_rev)
                    if svn_rev in git_commit.tags:
                        debug(f"skipping. svn rev {svn_rev} is already mapped to git commit {git_commit_number} = {git_commit.hash}")
                    else:
                        debug(f"mapping svn rev {svn_rev} to git commit {git_commit_number} = {git_commit.hash}")
                        #git_tag_env = default_env.copy()
                        #git_tag_env.update({
                        git_tag_env = {
                            'GIT_AUTHOR_DATE': git_commit.time,
                            'GIT_AUTHOR_NAME': git_commit.user,
                            'GIT_AUTHOR_EMAIL': git_commit.email,
                            'GIT_COMMITTER_DATE': git_commit.time,
                            'GIT_COMMITTER_NAME': git_commit.user,
                            'GIT_COMMITTER_EMAIL': git_commit.email,
                        }
                        run(
                            ["git", "tag", "-a", "-m", "", svn_rev, git_commit.hash],
                            cwd=git_repo_dir,
                            env=git_tag_env
                        )
                    last_svn_rev = svn_rev



            # TODO add dependency: git-lfs

            # TODO move large files to git-lfs
            # NOTE github lfs storage limit is 1GB per user for free accounts
            # -> store only large files (>50MB or >100MB) in git lfs
            # https://stackoverflow.com/questions/38768454/repository-size-limits-for-github-com
            # git lfs migrate import --above=1MiB # in my case, the largest source file is 640KB
            # or
            # git lfs migrate import --above=50MiB
            #
            # git-lfs is good for large binary files
            # not for medium-size text files (under 50 MB)
            # not for small binary files (problem: many small files -> bad performance). limit is around 0.5MB

            # github soft limit 50MiB
            # github hard limit 100MiB (larger files cannot be pushed to github)



            if False:
                # problem with branches: switching is expensive if main is large
                # -> store docs in a git tag (zero cost)
                #svn2git_branch = "gh-pages"
                svn2git_branch = "svn2git"
                info(f"adding {svn2git_branch} branch to document the svn2git mirroring process")
                branch_name = svn2git_branch
                # TODO check if branch exists
                # https://gist.github.com/ramnathv/2227408 # Creating a clean gh-pages branch

                try:
                    git_co = run(f"git checkout {branch_name}", cwd=git_repo_dir)
                except Exception as e:
                    debug(f"ignoring git error: {git_co.stderr}")
                    debug(f"git checkout failed. creating new branch {branch_name}")
                    # TODO check if branch exists
                    # https://gist.github.com/ramnathv/2227408 # Creating a clean gh-pages branch
                    run(f"git symbolic-ref HEAD refs/heads/{branch_name}", cwd=git_repo_dir)
                    try:
                        run("rm .git/index", cwd=git_repo_dir) # TODO why?
                    except Exception as e:
                        debug(f"ignoring error: {e}")
                    run("git clean -fdx", cwd=git_repo_dir)
                    #run("git reset --hard", cwd=git_repo_dir) # expensive

                with open(svn2git_rules_file, "r") as f:
                    svn2git_rules = f.read()
                md_file = f"{git_repo_dir}/readme.md"
                debug(f"writing md_file {md_file}")
                write_md_file(
                    md_file,
                    svn2github_url=svn2github_url, # const
                    git_repo_name=git_repo_name,
                    svn_url=svn_url,
                    svn2git_rules=svn2git_rules, # TODO escape for html <pre>
                )

                info(f"writing svn2github config file to git {branch_name} branch")
                doc_config_file = os.path.join(git_repo_dir, "svn2github.json")
                debug(f"doc_config_file = {doc_config_file}")
                with open(doc_config_file, "w") as f:
                    git_repo_url = f"https://github.com/{github_owner}/{github_repo}"
                    input_git_repo_url = git_repo_url
                    svnrepo_in_git_branch = 'svnrepo'

                    # TODO update config format
                    # create a new config
                    # this could be useful on "svn2github.py init"
                    # similar to "npm init -y"
                    doc_config = {
                        'name': git_repo_name,
                        'generator': 'https://github.com/milahu/svn2github',
                        'inputs': [
                            {
                                'type': 'svn',
                                'remotes': [
                                    {'url': svn_url}
                                ]
                            },
                            {
                                'type': 'git',
                                'branches': {
                                    'main': 'main',
                                    'svn2git': 'svn2git',
                                    'svnrepo': 'svnrepo',
                                },
                                'remotes': [
                                    {'url': input_git_repo_url}
                                ]
                            },
                        ],
                        'outputs': [
                            {
                                'type': 'git',
                                'branches': {
                                    'main': 'main',
                                    'svn2git': 'svn2git',
                                    'svnrepo': 'svnrepo',
                                },
                                'remotes': [
                                    {'url': git_repo_url}
                                ]
                            },
                        ]
                    }
                    #json.dump(doc_config, f, indent=2)

                    # write the actual config
                    # FIXME convert SimpleNamespace to dict
                    json.dump(config, f, indent=2)

                debug(f"copying rules file to git {branch_name} branch")
                doc_rules_file = os.path.join(git_repo_dir, os.path.basename(svn2git_rules_file))
                debug(f"doc_rules_file = {doc_rules_file}")
                shutil.copy(svn2git_rules_file, doc_rules_file)

                #sys.exit() # debug

                branch_size = int(run(f"git rev-list --count {branch_name}", cwd=git_repo_dir).stdout)
                debug(f"branch {branch_name}: branch size {branch_size}")
                message = "init" if branch_size == 0 else "update"

                run("git add .", cwd=git_repo_dir)
                try:
                    run(["git", "commit", "-m", message], cwd=git_repo_dir)
                except Exception as e:
                    # TODO only commit if git tree is dirty
                    # if git tree is clean, dont commit
                    warn(f"ignoring error: {e}")

                #sys.exit() # debug



        info("pushing all git repos to github")

        #svn2git_rules_file_list = glob.glob(git_repos_dir + "/*.rules")

        for svn2git_rules_file in svn2git_rules_file_list:
            debug(f"svn2git_rules_file = {svn2git_rules_file}")
            #svn2git_rules_file = os.path.basename(svn2git_rules_file)
            # convention: rules filename == f"{git_repo_name}.rules"
            git_repo_name = os.path.basename(svn2git_rules_file)[0:-6] # remove ".rules" suffix
            git_repo_dir = os.path.join(git_repos_dir, git_repo_name)
            debug(f"git_repo_dir = {git_repo_dir}")
            info(f"pushing git repo to github: {git_repo_dir}")
            # NOTE this will store your github token in .git/config
            try:
                # TODO suggest to change the remote-url in git
                # git -C ... remotes set-url github ...
                git_url = f"https://{github_username}:{github_token}@github.com/{github_owner}/{github_repo}"
                run(
                    ["git", "remote", "add", "github", git_url],
                    cwd=git_repo_dir
                )
            except Exception as e:
                warn(f"ignoring error: {e}")
            # NOTE "git push --tags" will push *all* local tags to remote
            # TODO always force?
            main_branch = "main"

            #debug(f"setting upstream branch. local:{main_branch} -> github:{main_branch}")
            #run(["git", "branch", "-u", f"github:{main_branch}", main_branch], cwd=git_repo_dir)

            # incremental push
            # large repos take forever to push
            # if the push crashes at 99%, nothing is pushed, and we must restart pushing from zero
            # -> split push into smaller steps, so on error, we can continue pushing
            # https://stackoverflow.com/questions/7757164/resuming-git-push
            # r=milahu; b=main; N=$(git rev-list --count $b); for i in $(seq $N -1000 0 | tail -n +2); do (set -x; git push $r $b~$i:$b); done && git push $r $b:$b
            commits_per_push = 1000
            num_commits = int(run(["git", "rev-list", "--count", main_branch], cwd=git_repo_dir).stdout)
            debug("pushing commits")
            debug(f"num_commits = {num_commits}")
            for skip_commits in range((num_commits - commits_per_push), 0, -1*commits_per_push):
                debug(f"push step. skip_commits = {skip_commits}")
                run(["git", "push", "-u", "github", f"{main_branch}~{skip_commits}:{main_branch}"], cwd=git_repo_dir)
            debug("last push")
            run(["git", "push", "-u", "github", main_branch], cwd=git_repo_dir) # last push of commits
            debug("pushing tags")
            run(["git", "push", "github", main_branch, "--tags"], cwd=git_repo_dir)
            #run(["git", "push", "github", "-u", main_branch, "--force", "--tags"], cwd=git_repo_dir)
            #run(["git", "push", "github", "-u", svn2git_branch, "--force"], cwd=git_repo_dir)
            #run(["git", "push", "github", "-u", svnrepo_branch, "--force"], cwd=git_repo_dir)



def main():

    parser = argparse.ArgumentParser(
        description="Mirror SVN repositories to GitHub",
        formatter_class=argparse.RawTextHelpFormatter
    )

    default_workdir = os.getcwd()
    parser.add_argument(
        "--workdir",
        "-C", # git -C
        help=inspect.cleandoc(f"""
            Set the work directory,
            which contains the svn2github.json config file.
            Default: Current directory.
        """),
        default=default_workdir,
        metavar="PATH",
    )

    parser.add_argument("--debug", help="print debug info", default=False, action="store_true")

    subparsers = parser.add_subparsers()

    subparser_import = subparsers.add_parser("init", help="Initialize a new mirror", aliases=['i'])
    subparser_import.set_defaults(command="init")
    subparser_import.add_argument("svn_url", metavar="SVN_URL", help="SVN repository (input)", default=None)
    subparser_import.add_argument("git_url", metavar="GIT_URL", help="Git repository (output)", default=None)

    subparser_update = subparsers.add_parser("update", help="Update an existing mirror", aliases=['u'])
    subparser_update.set_defaults(command="update")

    args = parser.parse_args(sys.argv[1:] or ["--help"])

    debug("argv =", sys.argv)
    debug("args =", args)

    sync_github_mirror(args)



if __name__ == "__main__":
    debug("call main")
    main()
