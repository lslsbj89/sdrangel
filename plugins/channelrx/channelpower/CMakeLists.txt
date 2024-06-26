project(channelpower)

set(channelpower_SOURCES
    channelpower.cpp
    channelpowersettings.cpp
    channelpowerbaseband.cpp
    channelpowersink.cpp
    channelpowerplugin.cpp
    channelpowerwebapiadapter.cpp
)

set(channelpower_HEADERS
    channelpower.h
    channelpowersettings.h
    channelpowerbaseband.h
    channelpowersink.h
    channelpowerplugin.h
    channelpowerwebapiadapter.h
)

include_directories(
    ${CMAKE_SOURCE_DIR}/swagger/sdrangel/code/qt5/client
)

if(NOT SERVER_MODE)
    set(channelpower_SOURCES
        ${channelpower_SOURCES}
        channelpowergui.cpp
        channelpowergui.ui
    )
    set(channelpower_HEADERS
        ${channelpower_HEADERS}
        channelpowergui.h
    )

    set(TARGET_NAME channelpower)
    set(TARGET_LIB "Qt::Widgets")
    set(TARGET_LIB_GUI "sdrgui")
    set(INSTALL_FOLDER ${INSTALL_PLUGINS_DIR})
else()
    set(TARGET_NAME channelpowersrv)
    set(TARGET_LIB "")
    set(TARGET_LIB_GUI "")
    set(INSTALL_FOLDER ${INSTALL_PLUGINSSRV_DIR})
endif()

add_library(${TARGET_NAME} SHARED
    ${channelpower_SOURCES}
)

target_link_libraries(${TARGET_NAME}
    Qt::Core
    ${TARGET_LIB}
    sdrbase
    ${TARGET_LIB_GUI}
)

install(TARGETS ${TARGET_NAME} DESTINATION ${INSTALL_FOLDER})

# Install debug symbols
if (WIN32)
    install(FILES $<TARGET_PDB_FILE:${TARGET_NAME}> CONFIGURATIONS Debug RelWithDebInfo DESTINATION ${INSTALL_FOLDER} )
endif()

