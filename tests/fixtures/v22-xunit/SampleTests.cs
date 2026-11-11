using Xunit;
namespace AutoMoto.V22.Tests;
public sealed class SampleTests
{
    [Fact]
    public void ArithmeticIsReal()
    {
        Assert.Equal(42, 21 + 21);
    }
}
