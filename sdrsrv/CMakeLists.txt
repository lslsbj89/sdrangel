project (sdrsrv)

set(sdrsrv_SOURCES
    maincore.cpp
    device/deviceset.cpp
    webapi/webapiadaptersrv.cpp
)

set(sdrsrv_HEADERS
    maincore.h
    device/deviceset.h
    webapi/webapiadaptersrv.h
)

if (LIMESUITE_FOUND)
  include_directories(${LIMESUITE_INCLUDE_DIR})
  set(sdrgui_LIMERFE_LIB ${LIMESUITE_LIBRARY})
endif (LIMESUITE_FOUND)

include_directories(
    ${CMAKE_SOURCE_DIR}/exports
    ${CMAKE_SOURCE_DIR}/sdrbase
    ${CMAKE_SOURCE_DIR}/logging
    ${CMAKE_SOURCE_DIR}/httpserver
    ${CMAKE_SOURCE_DIR}/swagger/sdrangel/code/qt5/client
    ${OPENGL_INCLUDE_DIR}
)

add_library(sdrsrv SHARED
    ${sdrsrv_SOURCES}
)

target_link_libraries(sdrsrv
    Qt5::Core
    Qt5::Multimedia
    sdrbase
    logging
)

install(TARGETS sdrsrv DESTINATION ${INSTALL_LIB_DIR})

