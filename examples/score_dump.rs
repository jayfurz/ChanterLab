//! Print the parsed note model for MusicXML files as JSON, keyed "path#verse",
//! for comparing against the web parser.
use chanterlab_core::score;

fn main() {
    let mut out = serde_json::Map::new();
    for path in std::env::args().skip(1) {
        let xml = std::fs::read_to_string(&path).expect("readable file");
        for verse in [1, 2] {
            let value = match score::parse(&xml, verse) {
                Ok(s) => serde_json::to_value(s).unwrap(),
                Err(e) => serde_json::json!({ "error": e.0 }),
            };
            out.insert(format!("{path}#{verse}"), value);
        }
    }
    println!("{}", serde_json::Value::Object(out));
}
