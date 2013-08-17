#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import os
import mozinstall
import re
import subprocess
import sys
import tempfile
import mozinfo

from mozfile import rmtree
from mozprofile import FirefoxProfile
from mozprofile import ThunderbirdProfile
from mozrunner import Runner
from mozrunner import LocalRunner
from optparse import OptionParser
from utils import strsplit, get_date, download_url, urlLinks
from ConfigParser import ConfigParser

subprocess._cleanup = lambda : None # mikeal's fix for subprocess threading bug
# XXX please reference this issue with a URL!

class Nightly(Runner):

    name = None # abstract base class

    def __init__(self, profile=None, repo_name=None, bits=mozinfo.bits, persist=None,
                       addons="", cmdargs=(), date=datetime.date.today()):
        if mozinfo.os == "win":
            if bits == 64:
                # XXX this should actually throw an error to be consumed by the caller
                print "No nightly builds available for 64 bit Windows"
                sys.exit()
            self.buildRegex = ".*win32.zip"
        elif mozinfo.os == "linux":
            if bits == 64:
                self.buildRegex = ".*linux-x86_64.tar.bz2"
            else:
                self.buildRegex = ".*linux-i686.tar.bz2"
        elif mozinfo.os == "mac":
            self.buildRegex = ".*mac.*\.dmg"
        self.addons = addons
        self.cmdargs = cmdargs
        self.profile = profile
        self.persist = persist
        self.repo_name = repo_name
        self._monthlinks = {}
        self.lastdest = None
        self.tempdir = None

    ### cleanup functions

    def remove_tempdir(self):
        if self.tempdir:
            rmtree(self.tempdir)
            self.tempdir = None

    def remove_lastdest(self):
        if self.lastdest:
            os.remove(self.lastdest)
            self.lastdest = None

    def cleanup(self):
        self.remove_tempdir()
        if not self.persist:
            self.remove_lastdest()

    __del__ = cleanup

    ### installation functions

    def get_destination(self, url, date):
        repo_name = self.repo_name or self.getRepoName(date)
        dest = os.path.basename(url)
        if self.persist is not None:
            date_str = date.strftime("%Y-%m-%d")
            dest = os.path.join(self.persist, "%s--%s--%s"%(date_str, repo_name, dest))
        return dest

    def download(self, date=datetime.date.today(), dest=None):
        url = self.getBuildUrl(date)
        if url:
            if not dest:
                dest = self.get_destination(url, date)
            if not self.persist:
                self.remove_lastdest()

            self.dest = self.lastdest = dest
            download_url(url, dest)
            return True
        else:
            return False

    def install(self, date=datetime.date.today()):
        if not self.download(date=date):
            print "Could not find nightly from %s" % date
            return False # download failed
        print "Installing nightly"
        if not self.name:
            raise NotImplementedError("Can't invoke abstract base class")
        self.remove_tempdir()
        self.tempdir = tempfile.mkdtemp()
        self.binary = mozinstall.get_binary(mozinstall.install(src=self.dest, dest=self.tempdir), self.name)
        return True

    def getBuildUrl(self, date):
        url = "http://ftp.mozilla.org/pub/mozilla.org/" + self.appName + "/nightly/"
        year = str(date.year)
        month = "%02d" % date.month
        day = "%02d" % date.day
        repo_name = self.repo_name or self.getRepoName(date)
        url += year + "/" + month + "/"

        linkRegex = '^' + year + '-' + month + '-' + day + '-' + '[\d-]+' + repo_name + '/$'
        cachekey = year + '-' + month
        if cachekey in self._monthlinks:
            monthlinks = self._monthlinks[cachekey]
        else:
            monthlinks = urlLinks(url)
            self._monthlinks[cachekey] = monthlinks

        # first parse monthly list to get correct directory
        for dirlink in monthlinks:
            dirhref = dirlink.get("href")
            if re.match(linkRegex, dirhref):
                # now parse the page for the correct build url
                for link in urlLinks(url + dirhref):
                    href = link.get("href")
                    if re.match(self.buildRegex, href):
                        return url + dirhref + href

        return False

    ### functions for invoking nightly

    def getAppInfo(self):
        parser = ConfigParser()
        ini_file = os.path.join(os.path.dirname(self.binary), "application.ini")
        parser.read(ini_file)
        try:
            changeset = parser.get('App', 'SourceStamp')
            repo = parser.get('App', 'SourceRepository')
            return (repo, changeset)
        except:
            return ("", "")

    def start(self, date=datetime.date.today(), wait=False):
        if not self.install(date):
            return False
            
        args = {}
        args['profile'] = self.profile
        args['addons'] = self.addons
        theRunner = LocalRunner.create(
                binary=self.binary,
                cmdargs=list(self.cmdargs),
                clean_profile=True,
                profile_args=args)
        print "theRunner: %s" % theRunner
        theRunner.start()
        if wait:
            try:
                theRunner.wait()
            except KeyboardInterrupt:
                theRunner.stop()
        #super(Runner, self).__init__(myProfile)
        #aRunner = Runner(binary=self.binary, cmdargs=list(self.cmdargs), profile=profile)
        # super(LocalRunner, self).__init__(

class ThunderbirdNightly(Nightly):
    appName = 'thunderbird'
    name = 'thunderbird'
    profile_class = ThunderbirdProfile

    def getRepoName(self, date):
        # sneaking this in here
        if mozinfo.os == "win" and date < datetime.date(2010, 03, 18):
           # no .zip package for Windows, can't use the installer
           print "Can't run Windows builds before 2010-03-18"
           sys.exit()
           # XXX this should throw an exception vs exiting without the error code

        if date < datetime.date(2008, 7, 26):
            return "trunk"
        elif date < datetime.date(2009, 1, 9):
            return "comm-central"
        elif date < datetime.date(2010, 8, 21):
            return "comm-central-trunk"
        else:
            return "comm-central"

class FirefoxNightly(Nightly):
    appName = 'firefox'
    name = 'firefox'
    profile_class = FirefoxProfile

    def getRepoName(self, date):
        if date < datetime.date(2008, 6, 17):
            return "trunk"
        else:
            return "mozilla-central"

class FennecNightly(Nightly):
    appName = 'mobile'
    name = 'fennec'
    profile_class = FirefoxProfile

    def __init__(self, repo_name=None, bits=mozinfo.bits, persist=None):
        super.__init__(self, repo_name, persist)
        self.buildRegex = 'fennec-.*\.apk'
        self.binary = 'org.mozilla.fennec/.App'
        self.persist = persist
        if "y" != raw_input("WARNING: bisecting nightly fennec builds will clobber your existing nightly profile. Continue? (y or n)"):
            raise Exception("Aborting!")

    def getRepoName(self, date):
        return "mozilla-central-android"

    def install(self):
        subprocess.check_call(["adb", "uninstall", "org.mozilla.fennec"])
        subprocess.check_call(["adb", "install", self.dest])
        return True

    def start(self, profile, addons, cmdargs):
        subprocess.check_call(["adb", "shell", "am start -n %s" % self.binary])
        return True

    def stop(self):
        # TODO: kill fennec (don't really care though since uninstalling it kills it)
        # PID = $(adb shell ps | grep org.mozilla.fennec | awk '{ print $2 }')
        # adb shell run-as org.mozilla.fennec kill $PID
        return True

def parseBits(optionBits):
    """returns the correctly typed bits"""
    if optionBits == "32":
        return 32
    else:
        # if 64 bits is passed on a 32 bit system, it won't be honored
        return mozinfo.bits

apps = {'thunderbird': ThunderbirdNightly,
        'fennec'     : FennecNightly,
        'firefox'    : FirefoxNightly}

def getApp(app):
    return apps[app]

def cli(args=sys.argv[1:]):
    """moznightly command line entry point"""
    
    # parse command line options
    parser = OptionParser()
    parser.add_option("-d", "--date", dest="date", help="date of the nightly",
                      metavar="YYYY-MM-DD", default=str(datetime.date.today()))
    parser.add_option("-a", "--addons", dest="addons",
                      help="list of addons to install",
                      metavar="PATH1,PATH2")
    parser.add_option("-p", "--profile", dest="profile", help="path to profile to user", metavar="PATH")
    parser.add_option("-n", "--app", dest="app", help="application name",
                      type="choice",
                      metavar="[%s]" % "|".join(apps.keys()),
                      choices=apps.keys(),
                      default="firefox")
    parser.add_option("-r", "--repo", dest="repo_name", help="repository name on ftp.mozilla.org",
                      metavar="[tracemonkey|mozilla-1.9.2]", default=None)
    parser.add_option("--bits", dest="bits", help="force 32 or 64 bit version (only applies to x86_64 boxes)",
                      choices=("32","64"), default=mozinfo.bits)
    parser.add_option("--persist", dest="persist", help="the directory in which files are to persist ie. /Users/someuser/Documents")
    options, args = parser.parse_args(args)

    options.bits = parseBits(options.bits)

    # XXX https://github.com/mozilla/mozregression/issues/50
    addons = strsplit(options.addons or "", ",")

    # run nightly
    anApp = getApp(options.app)
    runner = anApp(profile=options.profile, repo_name=options.repo_name, bits=options.bits,
                   persist=options.persist)
    runner.start(wait=True)

if __name__ == "__main__":
    cli()
