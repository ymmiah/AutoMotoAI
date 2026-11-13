@external(erlang, "erlang", "display")
fn display(message: String) -> Nil

pub fn main() {
  let answer = 6 * 7
  case answer {
    42 -> display("V30_GLEAM_PASS 42")
    _ -> panic as "Unexpected Gleam result"
  }
}
