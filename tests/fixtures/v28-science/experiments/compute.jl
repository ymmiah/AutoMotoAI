# V28 Julia numerical computation using the standard library only.
rows = readlines("data/measurements.csv")
@assert first(rows) == "value"
values = parse.(Float64, rows[2:end])
@assert length(values) == 5
total = sum(values)
average = total / length(values)
println("V28_JULIA_PASS count=$(length(values)) sum=$(Int(total)) mean=$(Int(average))")
