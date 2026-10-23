#include <stdio.h>
#include <string.h>
#include "tree_sitter/parser.h"

#define CHECK(value) \
  do { \
    if (!(value)) { \
      fprintf(stderr, "failed at line %d: %s\n", __LINE__, #value); \
      return 1; \
    } \
  } while (0)

extern void *tree_sitter_properties_external_scanner_create(void);
extern void tree_sitter_properties_external_scanner_destroy(void *);
extern bool tree_sitter_properties_external_scanner_scan(void *, TSLexer *, const bool *);
extern unsigned tree_sitter_properties_external_scanner_serialize(void *, char *);
extern void tree_sitter_properties_external_scanner_deserialize(void *, const char *, unsigned);

static bool eof(const TSLexer *lexer) {
  (void)lexer;
  return true;
}

int main(int argc, char **argv) {
  CHECK(argc == 2);
  void *first = tree_sitter_properties_external_scanner_create();
  void *second = tree_sitter_properties_external_scanner_create();
  TSLexer lexer = {.eof = eof};
  const bool valid[] = {true};
  char state[1024];
  memset(state, 0x55, sizeof(state));
  if (strcmp(argv[1], "serialize") == 0) {
    CHECK(tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
    unsigned length = tree_sitter_properties_external_scanner_serialize(first, state);
    CHECK(length == 1 && state[0] == 1);
    tree_sitter_properties_external_scanner_deserialize(first, state, length);
    CHECK(!tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
  } else if (strcmp(argv[1], "isolation") == 0) {
    CHECK(tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
    // Another parser resets between the first parser's scan and serialize.
    tree_sitter_properties_external_scanner_deserialize(second, NULL, 0);
    unsigned length = tree_sitter_properties_external_scanner_serialize(first, state);
    CHECK(length == 1 && state[0] == 1);
    tree_sitter_properties_external_scanner_deserialize(first, state, length);
    CHECK(!tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
    CHECK(tree_sitter_properties_external_scanner_scan(second, &lexer, valid));
  } else {
    CHECK(strcmp(argv[1], "reset") == 0);
    CHECK(tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
    CHECK(!tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
    // A failed scan must not silently make EOF available again.
    CHECK(!tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
    tree_sitter_properties_external_scanner_deserialize(first, NULL, 0);
    CHECK(tree_sitter_properties_external_scanner_scan(first, &lexer, valid));
  }
  tree_sitter_properties_external_scanner_destroy(first);
  tree_sitter_properties_external_scanner_destroy(second);
  return 0;
}
