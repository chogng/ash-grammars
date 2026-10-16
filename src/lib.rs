//! Process-lifetime Tree-sitter language functions from a verified platform bundle.
//!
//! `language` uses stable grammar names, independent of editor aliases or product queries.
//! Build scripts only link prepared libraries; they never compile grammar C or download files.

include!("languages.generated.rs");

#[cfg(test)]
mod tests {
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
