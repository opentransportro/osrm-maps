import os
import glob
import logging
import shutil
import subprocess
import threading
from datetime import date
from environs import Env
from github import Github

env = Env()
env.read_env()

app_path = os.path.abspath(os.getcwd())

# Override in .env for local development
LOG_LEVEL = env.str("LOG_LEVEL", 'INFO').upper()
MAP_URL = env.str("MAP_URL", default=None)
GH_REPO = env.str("GH_REPO", default=None)
GH_TOKEN = env.str("GH_TOKEN", default=None)


class ReleaseGenerator(object):
    def __init__(self, repo: str, token: str = None):
        self.token = token
        self.repo = repo
        self.logger = logging.getLogger('main-logger')

    def generate(self, files=None):
        if files is None:
            files = []

        if not (self.token is None or self.repo is None):
            g = Github(self.token)
            repo = g.get_repo(self.repo)

            self.__delete_release(str(date.today()), repo)
            self.__delete_release("latest", repo)

            self.__make_release(str(date.today()), repo, files)
            self.__make_release("latest", repo, files)
        else:
            self.logger.warning(
                "Skipping release generation since provided repo and tokens do no exist")

    @staticmethod
    def __make_release(name: str, repo, files):
        release = repo.create_git_release(name, "", "")
        import os
        for file in files:
            release.upload_asset(file, os.path.basename(file))

    @staticmethod
    def __delete_release(name, repo):
        try:
            release = repo.get_release(name)
            if not release is None:
                release.delete_release()
        except:
            pass


class LogPipe(threading.Thread):
    def __init__(self, level, logger=None):
        """Setup the object with a logger and a loglevel
        and start the thread
        """
        if logger is None:
            self.logger = logging.getLogger("gtfsexporter")
        else:
            self.logger = logger
        threading.Thread.__init__(self)
        self.daemon = False
        self.level = level
        self.fdRead, self.fdWrite = os.pipe()
        self.pipeReader = os.fdopen(self.fdRead)
        self.start()

    def fileno(self):
        """Return the write file descriptor of the pipe
        """
        return self.fdWrite

    def run(self):
        """Run the thread, logging everything.
        """
        for line in iter(self.pipeReader.readline, ''):
            self.logger.log(self.level, line.strip('\n'))

        self.pipeReader.close()

    def close(self):
        """Close the write end of the pipe.
        """
        os.close(self.fdWrite)


def run_command(args: [], logger=None) -> int:
    logpipe = LogPipe(logging.INFO, logger)
    # noinspection PyTypeChecker
    _result = 0

    with subprocess.Popen(args, stdout=logpipe, stderr=logpipe) as s:
        _result = s.wait()
        logpipe.close()
        logpipe.join()

    return _result


def check_utility(utility: str):
    logger = logging.getLogger('main-logger')
    if shutil.which(utility) is None:
        logger.error(f"no {utility} support, please install {utility} on your machine")
        exit(1)


def main():
    logging.basicConfig()
    logging.getLogger().setLevel(LOG_LEVEL)

    logger = logging.getLogger('main-logger')
    logger.setLevel(LOG_LEVEL)

    check_utility("docker")
    check_utility("wget")

    # we need url for map
    if MAP_URL is None:
        exit(1)

    run_command(["wget", "-O", "map.pbf", MAP_URL])
    run_command(["docker", "run", "-t",
                 "-v", f"{app_path}:/data",
                 "osrm/osrm-backend",
                 "osrm-extract", "-p", "/opt/car.lua", "/data/map.pbf"
                 ])
    run_command(["docker", "run", "-t",
                 "-v", f"{app_path}:/data",
                 "osrm/osrm-backend",
                 "osrm-partition", "/data/map.osrm"
                 ])
    run_command(["docker", "run", "-t",
                 "-v", f"{app_path}:/data",
                 "osrm/osrm-backend",
                 "osrm-customize", "/data/map.osrm"
                 ])

    run_command(["docker", "run", "-t",
                 "-v", f"{app_path}:/data",
                 "osrm/osrm-backend",
                 "chmod", "-R", "a+r", "/data/"
                 ])

    rg = ReleaseGenerator(GH_REPO, GH_TOKEN)
    rg.generate(glob.glob(os.path.join(app_path, "*.osrm*")))


if __name__ == "__main__":
    main()
