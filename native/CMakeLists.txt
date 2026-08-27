cmake_minimum_required(VERSION 3.24)
project(xiangqi_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(xiangqi_rules src/position.cpp)
target_include_directories(xiangqi_rules PUBLIC include)
if(MSVC)
  target_compile_options(xiangqi_rules PRIVATE /W4 /permissive- /EHsc)
else()
  target_compile_options(xiangqi_rules PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(xiangqi-engine src/main.cpp)
target_link_libraries(xiangqi-engine PRIVATE xiangqi_rules)

enable_testing()
add_executable(xiangqi-rules-tests tests/position_tests.cpp)
target_link_libraries(xiangqi-rules-tests PRIVATE xiangqi_rules)
add_test(NAME rules COMMAND xiangqi-rules-tests)

