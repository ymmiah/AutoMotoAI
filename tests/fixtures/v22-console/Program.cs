namespace AutoMoto.V22;
public static class Program
{
    public static int Main()
    {
        if (Math.Abs(21 + 21 - 42) > 0) return 1;
        Console.WriteLine("DOTNET_V22_SMOKE_PASS");
        return 0;
    }
}
