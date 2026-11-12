use strict;
use warnings;
use Test::More;
use lib 'lib';
use V27Sample;
is(V27Sample::combine(20, 22), 42, 'Perl arithmetic');
done_testing();
print "V27_PERL_FIXTURE_PASS\n";
