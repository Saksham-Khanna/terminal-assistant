"""Tests for multi-language AST-aware chunking."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from rag.ast_chunker import (
    chunk_python,
    chunk_source,
    language_for_extension,
)


def test_language_for_extension():
    assert language_for_extension("foo.py") == "python"
    assert language_for_extension("foo.js") == "javascript"
    assert language_for_extension("foo.tsx") == "javascript"
    assert language_for_extension("foo.java") == "java"
    assert language_for_extension("foo.go") == "go"
    assert language_for_extension("foo.rs") == "rust"
    assert language_for_extension("foo.txt") is None


def test_python_chunking_splits_functions_and_classes():
    source = """\
def alpha():
    return 1

def beta():
    return 2

class Gamma:
    def method(self):
        return 3
"""
    chunks = chunk_python(source)
    # alpha, beta, and the whole Gamma class each become a chunk.
    assert len(chunks) == 3
    assert "def alpha" in chunks[0]
    assert "def beta" in chunks[1]
    assert "class Gamma" in chunks[2]


def test_python_chunk_preserves_order_and_no_overlap():
    source = """\
def first():
    pass

def second():
    pass
"""
    chunks = chunk_python(source)
    assert len(chunks) == 2
    assert "first" in chunks[0] and "second" not in chunks[0]
    assert "second" in chunks[1]


def test_javascript_chunking_splits_functions_and_classes():
    source = """\
function greet(name) {
    return 'hello ' + name;
}

class Animal {
    constructor(name) {
        this.name = name;
    }
    speak() {
        return this.name;
    }
}

const arrow = () => 42;
"""
    chunks = chunk_source(source, "javascript")
    # Top-level units: the function declaration and the class. A top-level
    # arrow/const binding is not a cohesive unit node, so it isn't chunked
    # on its own (same tradeoff as Python module-level code).
    assert len(chunks) == 2
    assert "function greet" in chunks[0]
    assert "class Animal" in chunks[1]


def test_java_chunking_splits_classes_and_methods():
    source = """\
public class Foo {
    public int add(int a, int b) {
        return a + b;
    }
}

public interface Runnable {
    void run();
}
"""
    chunks = chunk_source(source, "java")
    # Top level: class Foo and interface Runnable.
    assert any("class Foo" in c for c in chunks)
    assert any("interface Runnable" in c for c in chunks)


def test_go_chunking_splits_functions_and_types():
    source = """\
package main

func main() {
    println("hi")
}

func helper(a int) int {
    return a + 1
}

type Point struct {
    X int
    Y int
}
"""
    chunks = chunk_source(source, "go")
    assert len(chunks) == 3
    assert "func main" in chunks[0]
    assert "func helper" in chunks[1]
    assert "type Point struct" in chunks[2]


def test_rust_chunking_splits_items():
    source = """\
fn main() {
    println!("hi");
}

struct Point {
    x: i32,
    y: i32,
}

enum Color {
    Red,
    Green,
}

impl Point {
    fn origin() -> Point {
        Point { x: 0, y: 0 }
    }
}
"""
    chunks = chunk_source(source, "rust")
    assert len(chunks) >= 4
    assert any("fn main" in c for c in chunks)
    assert any("struct Point" in c for c in chunks)
    assert any("enum Color" in c for c in chunks)
    assert any("impl Point" in c for c in chunks)


def test_unsupported_language_falls_back_to_lines():
    source = "line one\nline two\nline three\n"
    chunks = chunk_source(source, "unknown_language")
    # Falls back to line-window chunking; the whole file fits one chunk.
    assert chunks
    assert "line one" in chunks[0]


def test_syntax_error_falls_back_to_lines():
    source = "def broken(:\n    return\n"
    chunks = chunk_source(source, "python")
    # Parse fails -> line-window fallback still returns the content.
    assert chunks
    assert "def broken" in chunks[0]


def test_empty_source_when_no_units():
    # A Python file with only comments/directives has no units -> fallback.
    chunks = chunk_source("# just a comment line\n", "python")
    assert isinstance(chunks, list)


def test_chunk_python_backward_compat():
    source = "def x():\n    return 1\n"
    via_new = chunk_source(source, "python")
    via_old = chunk_python(source)
    assert via_new == via_old
