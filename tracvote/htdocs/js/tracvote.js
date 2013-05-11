$(document).ready(function() {
  $('#upvote, #downvote').click(function() {
    var button = this;
    var href;
    if (this.href.indexOf('?') === -1) {
      href = this.href + '?js=1';
    } else {
      href = this.href + '&js=1';
    }

    $.get(href, function(result) {
      result = result.split(':');

      $('#upvote img').attr('src', result[0]);
      $('#downvote img').attr('src', result[1]);
      $('#vote').attr('title', result[3])
      $('#votes').empty().prepend(result[2]);
      $(button).blur();
    });
    return false;
  });
});
