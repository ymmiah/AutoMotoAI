using NUnit.Framework;
namespace AutoMoto.V22.Tests;
[TestFixture]
public sealed class SampleTests
{
    [Test]
    public void ArithmeticIsReal()
    {
        Assert.That(20 + 22, Is.EqualTo(42));
    }
}
