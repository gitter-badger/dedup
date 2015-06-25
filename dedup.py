#!/usr/bin/env python

import hashlib
import os
import sys
 
# Set the directory you want to start from

topLevelList = {}

class dirObj():
    def __init__(self, name, parent=None):
        self.name=name
        self.files={}
        self.subdirs={}
        self.parent=parent

    def getLineage(self):
        if self.parent == None:
            return [ self.name ]
        ancestry=self.parent.getLineage()
        ancestry.append(self.name)
        return ancestry
    
    def display(self):
        print 'Directory ' + '/'.join(self.getLineage())
        for name, entry in self.subdirs.iteritems():
            entry.display()
        for name, entry in self.files.iteritems():
            entry.display();

    def placeDir(self, dirName):
        #print "looking to place " +  dirName + " in " + self.name
        dirList=dirName.split('/')
        if dirList.pop(0) != self.name:
            raise LookupError
        
        if len(dirList) == 0:
            return self

        nextDirName=dirList[0]
        if nextDirName in self.subdirs:
            #print "found " + nextDirName + " in " + self.name
            return self.subdirs[nextDirName].placeDir('/'.join(dirList))

        #print "did not find " + nextDirName + " in " + self.name
        nextDir=dirObj(nextDirName, self)
        self.subdirs[nextDirName]=nextDir
        return nextDir.placeDir('/'.join(dirList))

    def placeFile(self, fileName, parent = None):
        self.files[fileName]=fileObj(fileName, self)
    
class fileObj():
    def __init__(self, name, parent=None):
        self.name=name;
        self.parent=parent
    
    def display(self):
        if self.parent != None:
            print "File " + '/'.join(self.parent.getLineage()) + '/' + self.name
        else:
            print "File " + self.name
    
sys.argv.pop(0)

for entry in sys.argv:
    if os.path.isfile(entry):
        print 'Found a file:\t\t' + entry
        topLevelList[entry]=(fileObj(entry))
    elif os.path.isdir(entry):
        topDirEntry=dirObj(entry)
        topLevelList[entry]=topDirEntry
        for dirName, subdirList, fileList in os.walk(entry, topdown=False):
            dirEntry=topDirEntry.placeDir(dirName)
            for fname in fileList:
                print('\t\t\t%s/%s' % (dirName, fname))
                dirEntry.placeFile(fname)
            print('Found directory:\t%s' % dirName)
    else:
        print "I don't know what this is" + entry

print
for name, entry in topLevelList.iteritems():
    entry.display()


