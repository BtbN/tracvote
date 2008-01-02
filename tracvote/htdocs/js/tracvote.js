$(document).ready(function() {
  $('#upvote, #downvote').click(function() {
  var button = this;

    $.get(this.href + '?js=1', function(result) {
      result = result.split(':');

      $('#upvote img').attr('src', result[0]);
      $('#downvote img').attr('src', result[1]);
      $('#votes').attr('title', result[3]).empty().prepend(result[2]);
      $(button).blur();
    });
    return false;
  });
});
