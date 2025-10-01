import yaml
import os

BASE_PATH = "./"


def define_env(env):
    @env.macro
    def generateTemplateImgNameList():

        with open(BASE_PATH + "mkdocs.yml") as stream:
            splitConf = stream.read().split("nav:")

            navConfig = "nav:\n" + splitConf[1]

            try:
                navYaml = yaml.safe_load(navConfig)["nav"][1:]

                pageNameList = generatePageNameList(navYaml)

                imgNameList = generateImgNameList(pageNameList)

                return imgNameList

            except yaml.YAMLError as exc:
                print(exc)

    @env.macro
    def manual_button():
        return "[Přejít na manuál   :octicons-book-16:](manual.md){ .md-button }"


def generatePageNameList(navYaml):
    pageNameList = {}

    for PMODLinks in navYaml:

        key, val = list(PMODLinks.items())[0]
        name = key
        page = ""
        for link in val:
            dirName = link.split('/')[0]
            if dirName in getPMODDirs():
                page = dirName
                break

        pageNameList[page] = name

    return pageNameList


def getPMODDirs():
    projectDirs = []
    for root, dirs, files in os.walk(BASE_PATH + 'pmod'):
        projectDirs = dirs
        break

    blacklist = ['assets', 'template']
    filtered = []
    for dir in projectDirs:
        if dir not in blacklist:
            filtered.append(dir)

    return filtered


def generateImgNameList(pageNameList):
    imgNameList = []
    print(pageNameList  )

    for page, name in pageNameList.items():
        imgPath = page + "/assets/default.png"
        imgNameList.append((imgPath, name, page))

    return imgNameList
