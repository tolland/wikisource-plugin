plugins {
    idea
    id("ru.vyarus.use-python") version ("4.1.0")
}

idea {
    module {
        //if for some reason you want to add an extra sourceDirs
        sourceDirs.add(file("some-extra-source-folder"))
        name = "this"
    }
}

dependencies {
    //implementation("org.python:python") version("3.8.0")
}
