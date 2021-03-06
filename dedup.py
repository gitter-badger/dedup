#!/usr/bin/env python

import hashlib, os, sys, stat, time, gdbm

# TODO exclude and include filters

# CONSTANTS:

# This list represents files that may linger in directories 
# preventing this algorithm from recognizing them as empty.
# we market them as deletable, even if we do NOT have other
# copies available:
deleteList = [ "album.dat", "album.dat.lock", "photos.dat", "photos.dat.lock", "Thumbs.db", ".lrprev", "Icon\r", '.dropbox.cache', '.DS_Store' ]

# This list describes files and directories we do not want to risk
# messing with.  If we encounter these, never mark them as deletable.
doNotDeletList = []

# size of hashing buffer:
BUF_SIZE = 65536  

# default to quiet mode:
verbose=False

def resolve_candidates(candidates, currentDepth=None):
    """Helper function which examines a list of candidate objects with identical
    contents (as determined elsewhere) to determine which of the candidates is
    the "keeper" (or winner).  The other candidates are designated losers.

    The winner is selected by incrementally incrasing the directory depth (from 0)
    until one of the candidates is encountered. 

    TODO - other criteria?
    """
    depthMap={}
    losers = []

    for candidate in candidates:
        if currentDepth != None and candidate.depth > currentDepth:
            # this candidate is too deep
            continue
        if candidate.depth not in depthMap:
            # encountered a new candidate, lets store it
            depthMap[candidate.depth] = candidate
        else:
            # found another candidate at the same depth
            incumbent = depthMap[candidate.depth]
            # use pathname length as a tie-breaker
            if len(incumbent.pathname) > len(candidate.pathname):
                depthMap[candidate.depth] = candidate
            
    k=depthMap.keys()
    if len(k) == 0:
        # nothing to resolve at this depth
        return None, None

    k.sort()
    md=k.pop(0)
    # we choose the candidate closest to the root 
    # deeper candidates are the losers
    winner=depthMap[md]

    if isinstance(winner, DirObj) and winner.is_empty():
        # we trim empty directories using DirObj.prune_empty()
        # because it produces less confusing output
        return None, None

    # once we have a winner, mark all the other candidates as losers
    for candidate in candidates:
        if candidate != winner:
            losers.append(candidate)

    return winner, losers
        
def issocket(path):
    """For some reason python provides isfile and isdirectory but not issocket"""
    mode = os.stat(path).st_mode
    return stat.S_ISSOCK(mode)

def generate_delete(filename):
    # characters that we will wrap with double quotes:
    delimTestChars = set("'()")
    if any((c in delimTestChars) for c in filename):
        print 'rm -rf "' + filename + '"'
    else:
        print "rm -rf '" + filename + "'"

def check_int(s):
    if s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()

def check_level(pathname):
    parts=pathname.split(':')
    if len(parts) > 1:
        firstPart=parts.pop(0)
        remainder=':'.join(parts)
        if check_int(firstPart):
            return int(firstPart), remainder

    # if anything goes wrong just fail back to assuming the whole thing is a path
    return 0, pathname

class EntryList:
    """A container for all source directories and files to examine"""
    def __init__(self, arguments, databasePathname, staggerPaths):
        self.contents = {}
        self.modTime = None
        self.db = None
        stagger=0;

        if databasePathname != None:
            try:
                self.modTime = os.stat(databasePathname).st_mtime
            except OSError:
                print "# db " + databasePathname + " doesn't exist yet"
                self.modTime = None

            self.db = gdbm.open(databasePathname, 'c')
            if self.modTime == None:
                self.modTime = time.time()

            print '# db last modification time is ' + str(time.time() - self.modTime) + ' seconds ago'

        # walk arguments adding files and directories
        for entry in arguments:
            # strip trailing slashes, they are not needed
            entry=entry.rstrip('/')

            # check if a weight has been provided for this argument
            weightAdjust, entry = check_level(entry)

            if os.path.isfile(entry):
                if staggerPaths:
                    weightAdjust=weightAdjust + stagger
                self.contents[entry]=FileObj(entry, dbTime=self.modTime, db=self.db, weightAdjust=weightAdjust)
                if staggerPaths:
                    stagger=stagger + self.contents[entry].depth
            elif issocket(entry):
                print '# Skipping a socket ' + entry
            elif os.path.isdir(entry):
                if staggerPaths:
                    weightAdjust=weightAdjust + stagger
                topDirEntry=DirObj(entry, weightAdjust)
                self.contents[entry]=topDirEntry
                for dirName, subdirList, fileList in os.walk(entry, topdown=False):
                    dirEntry=topDirEntry.place_dir(dirName, weightAdjust)
                    for fname in fileList:
                        if issocket(dirEntry.pathname + '/' + fname):
                            print '# Skipping a socket ' + dirEntry.pathname + '/' + fname
                        else:
                            dirEntry.files[fname]=FileObj(fname, parent=dirEntry, dbTime=self.modTime, db=self.db, weightAdjust=weightAdjust)
                if staggerPaths:
                    stagger=topDirEntry.max_depth()
            else:
                print "I don't know what this is" + entry
                sys.exit()
        if self.db != None:
            self.db.close()

    def count_deleted_bytes(self):      # EntryList.count_deleted_bytes
        """Returns a count of all the sizes of the deleted objects within"""
        bytes=0
        for name, e in self.contents.iteritems():
            bytes = bytes + e.count_deleted_bytes()
        return bytes

    def count_deleted(self):            # EntryList.count_deleted
        """Returns a count of all the deleted objects within"""
        count=0
        for name, e in self.contents.iteritems():
            count = count + e.count_deleted()
        return count

    def prune_empty(self):              # EntryList.prune_empty
        """Crawls through all directories and deletes the children of the deleted"""
        prevCount = self.count_deleted()
        for name, e in allFiles.contents.iteritems():
            e.prune_empty()
        return allFiles.count_deleted() - prevCount

    def walk(self):                     # EntryList.walk
        for name, topLevelItem in allFiles.contents.iteritems():
            for item in topLevelItem.walk():
                yield item

    def generate_commands(self):        # EntryList.generate_commands
        """Generates delete commands to dedup all contents"""

        selectDirMap={}
        selectFileMap={}
        emptyMap={}

        # TODO file removals should be grouped by the winner for better reviewing
        for name, e in self.contents.iteritems():
            e.generate_commands(selectDirMap, selectFileMap, emptyMap)

        winnerList=selectDirMap.keys()
        if len(winnerList):
            print '####################################################################'
            print '# redundant directories:'
            winnerList.sort()
            for winner in winnerList:
                losers=selectDirMap[winner]
                print "#      '" + winner + "'"
                for loser in losers:
                    generate_delete(loser)
                print

        winnerList=selectFileMap.keys()
        if len(winnerList):
            print '####################################################################'
            print '# redundant files:'
            winnerList.sort()
            for winner in winnerList:
                losers=selectFileMap[winner]
                print "#      '" + winner + "'"
                for loser in losers:
                    generate_delete(loser)
                print
        
        emptyDirs=emptyMap.keys()
        if len(emptyDirs):
            print '####################################################################'
            print '# directories that are or will be empty after resolving duplicates:'
            emptyDirs.sort()
            for emptyDir in emptyDirs:
                generate_delete(emptyDir)

class HashMap:
    """A wrapper to a python dict with some helper functions"""
    def __init__(self,allFiles):
        self.contentHash = {}
        self.minDepth = 1
        self.maxDepth = 0
        self.allFiles=allFiles # we will use this later to count deletions

        for name, e in allFiles.contents.iteritems():
            if isinstance(e, FileObj):
                self.add_entry(e)
            else:
                for dirEntry in e.dirwalk():
                    #print '\n# adding dir ' + dirEntry.pathname
                    if not dirEntry.deleted:
                        for name, fileEntry in dirEntry.files.iteritems():
                            if not fileEntry.deleted:
                                self.add_entry(fileEntry)
                                #print '# added file ' + fileEntry.pathname
                            else:
                                #print '# skipping deleted file ' + fileEntry.pathname
                                pass
                        dirEntry.finalize()
                        self.add_entry(dirEntry)
                        #print '# added dir ' + dirEntry.pathname
                    else:
                        #print '# skipping deleted dir ' + dirEntry.pathname
                        pass

            maxd=e.max_depth()
            if self.maxDepth < maxd:
                self.maxDepth=maxd

    def add_entry(self, entry):                 # Hashmap.add_entry
        """Store a file or directory in the HashMap, indexed by it's hash"""

        if entry.hexdigest in self.contentHash:
            self.contentHash[entry.hexdigest].append(entry)
        else:
            self.contentHash[entry.hexdigest] = [ entry ]

        if entry.depth < self.minDepth:
            self.minDepth = entry.depth

    def display(self):                          # Hashmap.display
        """Generate a human readable report."""
        for hashval, list in self.contentHash.iteritems():
            for entry in list:
                entry.display(False, False)

    def delete(self, entry):                    # Hashmap.delete
        """Marks an entry as deleted then remove it from the HashMap"""

        entry.delete()

        # remove the entry from the hashmap
        list=self.contentHash[entry.hexdigest]
        newlist = []
        for e in list:
            if e != entry:
                newlist.append(e)

        # if there are no more entries for this hashval, remove
        # it from the dictionary m
        if len(newlist):
            self.contentHash[entry.hexdigest] = newlist
        else:
            del self.contentHash[entry.hashval]

        # also remove all the deleted children from the hashmap
        self.prune()

    def prune(self):                            # HashMap.prune
        """Removes deleted objects from the HashMap"""
        for hashval, list in self.contentHash.iteritems():
            newlist=[]
            for entry in list:
                if not entry.deleted:
                    newlist.append(entry)
            self.contentHash[hashval]=newlist

    def resolve(self):                          # HashMap.resolve
        """Compares all entries and where hash collisions exists, pick a keeper"""
        prevCount = self.allFiles.count_deleted()

        # no need to resolve uniques, so remove them from the HashMap
        deleteList=[]
        for hashval, list in self.contentHash.iteritems():
            if len(list) == 1:
                deleteList.append(hashval)
        for e in deleteList:
            del self.contentHash[e]

        # delete the directories first, in order of
        # increasing depth
        if verbose:
            print '# checking candidates from depth ' + str(self.minDepth) + ' through ' + str(self.maxDepth)
        for currentDepth in xrange(self.minDepth-1,self.maxDepth+1):
            for hashval, list in self.contentHash.iteritems():
                example = list[0]
                if isinstance(example, DirObj):
                    winner, losers = resolve_candidates(list, currentDepth)
                    if losers != None:
                        for loser in losers:
                            if not loser.deleted:
                                if verbose:
                                    print '# dir "' + loser.pathname + '" covered by "' + winner.pathname + '"'
                                self.delete(loser)
                                loser.winner = winner
                        self.prune()

        for hashval, list in self.contentHash.iteritems():
            example = list[0]  
            if isinstance(example, FileObj):
                winner, losers = resolve_candidates(list)
                for loser in losers:
                    if not loser.deleted:
                        if verbose:
                            print '# file "' + loser.pathname + '" covered by "' + winner.pathname + '"'
                        self.delete(loser)
                        loser.winner = winner

        return self.allFiles.count_deleted() - prevCount

class DirObj():
    """A directory object which can hold metadata and references to files and subdirectories"""
    def __init__(self, name, weightAdjust=0, parent=None):
        self.name=name
        self.files={}
        self.deleted=False
        self.winner = None
        self.subdirs={}
        self.weightAdjust=weightAdjust
        self.parent=parent
        ancestry=self.get_lineage()
        self.pathname='/'.join(ancestry) 
        self.depth=len(ancestry) + self.weightAdjust
        self.ignore=self.name in deleteList
        #if verbose:
        #    print '# ' + self.pathname + ' has an adjusted depth of ' + str(self.depth)

    def get_lineage(self):                      # DirObj.get_lineage
        """Crawls back up the directory tree and returns a list of parents"""
        if self.parent == None:
            return self.name.split('/')
        ancestry=self.parent.get_lineage()
        ancestry.append(self.name)
        return ancestry

    def max_depth(self):                        # DirObj.max_depth
        """Determine the deepest point from this directory"""
        md=self.depth
        if len(self.subdirs.keys()):
            for name, entry in self.subdirs.iteritems():
                if not entry.deleted:
                    td = entry.max_depth()
                    if td > md:
                        md=td
            return md
        elif len(self.files.keys()):
            return md + 1
        else:
            return md
    
    def display(self, contents=False, recurse=False):  # DirObj.display
        """Generate a human readable report.
                'contents' controls if files are displayed
                'recurse' controls if subdirs are displayed
        """
        if recurse:
            for name, entry in self.subdirs.iteritems():
                entry.display(contents, recurse)
        if contents:
            for name, entry in self.files.iteritems():
                entry.display(contents, recurse);
        print '# Directory\t' + str(self.deleted) + '\t' + str(self.ignore) + '\t' + str(self.depth) + '\t' + self.hexdigest + ' ' + self.pathname

    def place_dir(self, inputDirName, weightAdjust):    # DirObj.place_dir
        """Matches a pathname to a directory structure and returns a DirObj"""
        #print "looking to place " +  inputDirName + " in " + self.name
        inputDirList=inputDirName.split('/')
        nameList=self.name.split('/')

        while (len(inputDirList) and len(nameList)):
            x=inputDirList.pop(0)
            y=nameList.pop(0)
            if x != y:
                print x + ' and ' + y + ' do not match'
                raise LookupError
        
        if len(inputDirList) == 0:
            return self

        nextDirName=inputDirList[0]
        if nextDirName in self.subdirs:
            #print "found " + nextDirName + " in " + self.name
            return self.subdirs[nextDirName].place_dir('/'.join(inputDirList), weightAdjust)

        #print "did not find " + nextDirName + " in " + self.name
        nextDir=DirObj(nextDirName, weightAdjust, self)
        self.subdirs[nextDirName]=nextDir
        return nextDir.place_dir('/'.join(inputDirList), weightAdjust)

    def dirwalk(self, topdown=False):                      # DirObj.dirwalk
        """A generator which traverses just subdirectories"""
        if topdown:
            yield self

        for name, d in self.subdirs.iteritems():
            for dirEntry in d.dirwalk():
                yield dirEntry

        if not topdown:
            yield self

    def walk(self):                                         # DirObj.walk
        """A generator which traverses files and subdirs"""
        for name, subdir in self.subdirs.iteritems():
            for e in subdir.walk():
                yield e
        for name, fileEntry in self.files.iteritems():
            yield fileEntry
        yield self
            
    def delete(self):                                   # DirObj.delete
        """Mark this directory and all children as deleted"""
        self.deleted=True
        for name, d in self.subdirs.iteritems():
            d.delete()
        for name, f in self.files.iteritems():
            f.delete()

    def generate_commands(self, selectDirMap, selectFileMap, emptyMap):             # DirObj.generate_commands
        """Generates delete commands to dedup all contents of this dir"""
        if self.deleted:
            if self.winner != None:
                if self.winner.pathname in selectDirMap:
                    selectDirMap[self.winner.pathname].append(self.pathname)
                else:
                    selectDirMap[self.winner.pathname] = [ self.pathname ]
            else:
                emptyMap[self.pathname]=True
        else:
            for fileName, fileEntry in self.files.iteritems():
                fileEntry.generate_commands(selectDirMap, selectFileMap, emptyMap)
            for dirName, subdir in self.subdirs.iteritems():
                subdir.generate_commands(selectDirMap, selectFileMap, emptyMap)

    def is_empty(self):                                 # DirObj.is_empty
        """Checks if the dir is empty, ignoring items marked as deleted or ignored"""

        for fileName, fileEntry in self.files.iteritems():
            if not fileEntry.deleted and not fileEntry.ignore:
                #print '# ' + self.pathname + ' is not empty due to a file ' + fileEntry.name
                return False

        for dirName, subdir in self.subdirs.iteritems():
            if not subdir.deleted and not subdir.is_empty() and not subdir.ignore:
                #print '# ' + self.pathname + ' is not empty due to a dir ' + subdir.name
                return False

        #print '# ' + self.pathname + ' is empty!'
        return True

    def prune_empty(self):                              # DirObj.prune_empty
        """Crawls through all directories and marks the shallowest empty entiries for deletion"""
        #print '# checking ' + self.pathname + ' for empties'
        if self.is_empty() and not self.deleted and self.parent == None:
            self.delete()
            #print '# TLD ' + self.pathname + ' is now empty: ' + str(self.is_empty())
        elif self.is_empty() and not self.deleted and self.parent != None and not self.parent.is_empty():
            self.delete()
            #print '# ' + self.pathname + ' is now empty: ' + str(self.is_empty())
        else:
            #print '# ' + self.pathname + ' is not empty: ' + str(self.is_empty())
            for dirname, dirEntry in self.subdirs.iteritems():
                dirEntry.prune_empty()

    def finalize(self):                                 # DirObj.finalize
        """Once no more files or directories are to be added, we can 
        create a meta-hash of all the hashes therein.  This allows us to
        test for directories which have the same contents.
        """
        digests=[]
        for filename, fileEntry in self.files.iteritems():
            digests.append(fileEntry.hexdigest)
        for dirname, dirEntry in self.subdirs.iteritems():
            digests.append(dirEntry.hexdigest)
        digests.sort()
        sha1 = hashlib.sha1()
        for d in digests:
            sha1.update(d)
        self.hexdigest=sha1.hexdigest()

    def count_deleted_bytes(self):                      # DirObj.count_deleted_bytes
        """returns a count of all the sizes of the deleted objects within"""
        bytes=0
        for name, d in self.subdirs.iteritems():
            bytes = bytes + d.count_deleted_bytes()
        for name, f in self.files.iteritems():
            if f.deleted:
                bytes = bytes + f.count_deleted_bytes()
        return bytes

    def count_deleted(self):                            # DirObj.count_deleted
        """returns a count of all the deleted objects within"""
        if self.deleted:
            deleted=1
        else:
            deleted=0
        for name, d in self.subdirs.iteritems():
            deleted = deleted + d.count_deleted()
        for name, f in self.files.iteritems():
            if f.deleted:
                deleted = deleted + 1
        return deleted

class FileObj():
    """A file object which stores some metadata"""
    def __init__(self, name, parent=None, dbTime=None, db=None, weightAdjust=0):
        self.name=name;
        self.winner=None
        self.parent = parent
        self.deleted=False
        self.weightAdjust=weightAdjust
        self.ignore=self.name in deleteList

        if self.parent != None:
            ancestry=self.parent.get_lineage()
            self.pathname='/'.join(ancestry) + '/' + self.name
            self.depth=len(ancestry) + self.weightAdjust
        else:
            self.pathname=self.name
            self.depth=self.weightAdjust
        #if verbose:
        #    print '# ' + self.pathname + ' has an adjusted depth of ' + str(self.depth)

        statResult = os.stat(self.pathname)
        self.modTime = statResult.st_mtime
        self.createTime = statResult.st_ctime
        self.bytes = statResult.st_size
        if self.bytes == 0:
            self.ignore = True
            self.hexdigest='da39a3ee5e6b4b0d3255bfef95601890afd80709'
            return

        if db != None:
            #print '# ' + self.pathname + ' is ' + str(dbTime - self.modTime) + ' seconds older than the db.'
            pass

        if db != None and self.pathname in db:
            # we've a cached hash value for this pathname
            if self.modTime > dbTime:
                # file is newer than db
                #print '# ' + self.pathname + ' is newer than the db'
                pass
            else:
                # db is newer than file
                if verbose:
					print '# ' + self.pathname + ' already in db'
                self.hexdigest=db[self.pathname]
                return
        elif db != None:
            #print '# ' + self.pathname + ' not in db'
            pass

        # open and read the file
        sha1 = hashlib.sha1()
        with open(self.pathname, 'rb') as f:
            while True:
                data = f.read(BUF_SIZE)
                if not data:
                    break
                sha1.update(data)
        self.hexdigest=sha1.hexdigest()

        if verbose:
			print '# computed new hash for ' + self.pathname

        if db != None:
            # add/update the cached hash value for this entry
            #if self.pathname in db:
            #    print '# updating db entry for ' + self.pathname
            #else:
            #    print '# inserting db entry for ' + self.pathname
            db[self.pathname]=self.hexdigest

    def max_depth(self):                # FileObj.max_depth
        return self.depth

    def walk(self):                     # FileObj.walk
        """Used to fit into other generators"""
        yield self

    def delete(self):                   # FileObj.delete
        """Mark for deletion"""
        self.deleted=True

    def generate_commands(self, selectDirMap, selectFileMap, emptyMap):     # FileObj.generate_commands
        """Generates delete commands to dedup all contents"""
        if self.deleted and not self.ignore:
            if self.winner != None:
                if self.bytes != self.winner.bytes:
                    print '# BIRTHDAY CRISIS! matched hashes and mismatched sizes!'
                    sys.exit(-1)
                if self.winner.pathname in selectFileMap:
                    selectFileMap[self.winner.pathname].append(self.pathname)
                else:
                    selectFileMap[self.winner.pathname] = [self.pathname]
            else:
                emptyMap[self.pathname] = True

    def prune_empty(self):                      # FileObj.prune_empty
        """Crawls through all directories and deletes the children of the deleted"""
        return False            # can't prune a file

    def display(self, contents=False, recurse=False):  # FileObj.display
        """Generate a human readable report."""
        print '# File\t\t' + str(self.deleted) + '\t' + str(self.ignore) + '\t' + str(self.depth) + '\t' + self.hexdigest + ' ' + self.pathname + ' '

    def count_deleted_bytes(self):              # FileObj.count_deleted_bytes
        """Returns a count of all the sizes of the deleted objects within"""
        if self.deleted:
             return self.bytes 
        else:
            return 0

    def count_deleted(self):                    # FileObj.count_deleted
        """Returns a count of all the deleted objects within"""
        if self.deleted:
             return 1
        else:
            return 0

def clean_database(databasePathname):
    """function to remove dead nodes from the hash db"""
    print '# loading database ' + databasePathname
    try:
        db = gdbm.open(databasePathname, 'w')
    except:
        print "# " + databasePathname + " could not be loaded"
        sys.exit(-1)

    # even though gdbm supports memory efficient iteration over
    # all keys, I want to order my traversal across similar
    # paths to leverage caching of directory files:
    allKeys=db.keys()
    print '# finished loaded keys from ' + databasePathname
    allKeys.sort()
    print '# finished sorting keys from ' + databasePathname
    print '# deleting dead nodes'
    count=0
    for currKey in allKeys:
        try:
            os.stat(currKey)
            sys.stdout.write('.')
        except OSError:
            del db[currKey]
            sys.stdout.write('*')
            count=count+1
        sys.stdout.flush()
    print "\n# reorganizing " + databasePathname
    db.reorganize()
    db.sync()
    db.close()
    print '# done cleaning ' + databasePathname + ', removed ' + str(count) + ' dead nodes!'

if __name__ == '__main__':
    startTime=time.time()
    sys.argv.pop(0)             # do away with the command itself

    # defaults
    databasePathname=None
    cleanDatabase=False
    staggerPaths=False
    again=True
    while again:
        try:
            nextArg=sys.argv[0]     # peek ahead
        except IndexError:
            break                   # no more args
        again=False
        if nextArg == '-v' or nextArg == '--verbose':
            sys.argv.pop(0)
            again=True
            verbose=True
        if nextArg == '-db' or nextArg == '--database':
            sys.argv.pop(0)
            try:
                databasePathname=sys.argv.pop(0)
            except IndexError:
                print '# argument needed for -db switch'
                sys.exit(-1)
            again=True
        if nextArg == '-cdb' or nextArg == '--clean-database':
            sys.argv.pop(0)
            cleanDatabase=True
            again=True
        if nextArg == '-s' or nextArg == '--stagger-paths':
            sys.argv.pop(0)
            staggerPaths=True
            again=True

    if databasePathname != None:
        print '# set to use database: ' + databasePathname
        if cleanDatabase:
            clean_database(databasePathname)
            sys.exit(0)
    elif cleanDatabase:
        print '# database file must be specified for --clean-database command (use -db)'
        sys.exit(-1)

    allFiles = EntryList(sys.argv, databasePathname, staggerPaths)
    print '# files loaded'
    passCount=0
    deleted=1                   # fake value to get the loop started
    while deleted > 0:          # while things are still being removed, keep working

        h = HashMap(allFiles)
        deletedDirectories = allFiles.prune_empty()

        h = HashMap(allFiles)
        deletedHashMatches = h.resolve()

        deleted = deletedDirectories + deletedHashMatches
        passCount = passCount + 1
        if deleted > 0:
            print '# ' + str(deleted) + ' entries deleted on pass ' + str(passCount)

    allFiles.generate_commands()

    #for e in allFiles.walk():
    #    e.display(False,False)
    endTime=time.time()
    print '# total bytes marked for deletion (not including directory files): ' + str(allFiles.count_deleted_bytes()) + '\n'
    print '# total running time: ' + str(endTime - startTime) + ' seconds.'

# vim: set expandtab sw=4 ts=4:
