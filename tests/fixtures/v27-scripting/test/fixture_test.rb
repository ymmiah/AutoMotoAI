# No third-party gems or arbitrary package installation needed.
require_relative '../lib/sample'
raise 'incorrect Ruby arithmetic' unless V27Sample.combine(20, 22) == 42
puts 'V27_RUBY_FIXTURE_PASS'
