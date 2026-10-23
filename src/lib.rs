//! Process-lifetime Tree-sitter language functions from a verified platform bundle.
//!
//! `language` uses stable grammar names, independent of editor aliases or product queries.
//! Build scripts only link prepared libraries; they never compile grammar C or download files.

include!("languages.generated.rs");

#[cfg(test)]
mod tests {
    #[test]
    fn concurrent_properties_parsers_finish_at_eof() {
        let start = std::sync::Barrier::new(8);
        let text = "key=value\n".repeat(100);
        std::thread::scope(|scope| {
            for _ in 0..8 {
                let start = &start;
                let text = &text;
                scope.spawn(move || {
                    let language: tree_sitter::Language =
                        super::language("properties").unwrap().into();
                    start.wait();
                    for iteration in 0..128 {
                        let input = if iteration % 2 == 0 {
                            "x"
                        } else {
                            text.as_str()
                        };
                        let mut parser = tree_sitter::Parser::new();
                        parser.set_language(&language).unwrap();
                        let mut checks = 0;
                        let mut progress = |_: &tree_sitter::ParseState| {
                            checks += 1;
                            if checks >= 1_000 {
                                std::ops::ControlFlow::Break(())
                            } else {
                                std::ops::ControlFlow::Continue(())
                            }
                        };
                        // Bound the test's work if the scanner starts replaying an
                        // empty EOF token; the old scanner can otherwise exhaust RAM.
                        let tree = parser
                            .parse_with_options(
                                &mut |offset, _| &input.as_bytes()[offset.min(input.len())..],
                                None,
                                Some(
                                    tree_sitter::ParseOptions::new()
                                        .progress_callback(&mut progress),
                                ),
                            )
                            .expect("Properties parser stalled at EOF");
                        assert_eq!(tree.root_node().end_byte(), input.len());
                        assert!(!tree.root_node().has_error());
                    }
                });
            }
        });
    }

    #[test]
    fn every_bundled_grammar_loads_and_parses() {
        for name in super::GRAMMARS {
            let language: tree_sitter::Language = super::language(name).unwrap().into();
            let mut parser = tree_sitter::Parser::new();
            parser
                .set_language(&language)
                .unwrap_or_else(|error| panic!("{name}: {error}"));
            assert!(parser.parse("", None).is_some(), "{name}");
        }
        assert!(super::language("not-a-grammar").is_none());
    }
}
